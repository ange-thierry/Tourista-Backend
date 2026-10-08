from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

from core.constants import RESTRICTED_SIGNUP_ROLES, UserRole

from .models import User
from .tokens import email_verification_token


class UserSerializer(serializers.ModelSerializer):
    """Matches the frontend `User` interface: {id, email, name, role, avatar, ...}."""

    id = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    emailVerified = serializers.BooleanField(source='email_verified', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'role', 'avatar', 'phone', 'emailVerified']
        read_only_fields = ['id', 'email', 'role']

    def get_id(self, obj) -> str:
        return str(obj.pk)

    def get_avatar(self, obj) -> str:
        return obj.avatar_url


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['name', 'avatar', 'phone']


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    name = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(choices=UserRole.choices, default=UserRole.TOURIST)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate_role(self, value):
        if value in RESTRICTED_SIGNUP_ROLES:
            raise serializers.ValidationError('This role cannot be self-assigned.')
        return value

    def validate(self, attrs):
        password_validation.validate_password(attrs['password'])
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            name=validated_data['name'].strip(),
            role=validated_data['role'],
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get('request'),
            email=attrs['email'].strip().lower(),
            password=attrs['password'],
        )
        if user is None:
            raise serializers.ValidationError('Invalid email or password.')
        if not user.is_active:
            raise serializers.ValidationError('This account is disabled.')
        attrs['user'] = user
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, self.context['request'].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class _UidTokenSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    token_generator = default_token_generator
    invalid_message = 'This link is invalid or has expired.'

    def validate(self, attrs):
        try:
            pk = force_str(urlsafe_base64_decode(attrs['uid']))
            user = User.objects.get(pk=pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError(self.invalid_message)
        if not self.token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError(self.invalid_message)
        attrs['user'] = user
        return attrs


class PasswordResetConfirmSerializer(_UidTokenSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        password_validation.validate_password(attrs['password'], attrs['user'])
        return attrs


class VerifyEmailSerializer(_UidTokenSerializer):
    token_generator = email_verification_token
    invalid_message = 'This verification link is invalid or has already been used.'
