"""Authentication.

The refresh token is set as an httpOnly cookie (scoped to /api/auth/) and never
exposed to JavaScript; responses only carry the short-lived access token, which
the frontend keeps in memory. Non-browser clients may still send `{"refresh": ...}`
in the body of /auth/refresh/ and /auth/logout/.
"""

from django.conf import settings
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from bookings.services import claim_guest_bookings
from core.emails import send_password_reset_email, send_verification_email

from .models import User
from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
    UserUpdateSerializer,
    VerifyEmailSerializer,
)
from .tokens import email_verification_token


def set_refresh_cookie(response: Response, refresh: str) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh,
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH, samesite=settings.REFRESH_COOKIE_SAMESITE
    )


def session_response(user: User, status_code=status.HTTP_200_OK) -> Response:
    refresh = RefreshToken.for_user(user)
    response = Response(
        {'user': UserSerializer(user).data, 'access': str(refresh.access_token)}, status=status_code
    )
    set_refresh_cookie(response, str(refresh))
    return response


def _incoming_refresh(request) -> str | None:
    return request.COOKIES.get(settings.REFRESH_COOKIE_NAME) or request.data.get('refresh')


def revoke_all_sessions(user: User) -> None:
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def issue_verification(user: User) -> None:
    send_verification_email(user, email_verification_token.make_token(user))


class AuthThrottleMixin:
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'


class RegisterView(AuthThrottleMixin, APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        issue_verification(user)
        return session_response(user, status.HTTP_201_CREATED)


class LoginView(AuthThrottleMixin, APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        return session_response(serializer.validated_data['user'])


class RefreshView(AuthThrottleMixin, APIView):
    """Exchange the refresh cookie for a new access token (and rotate the cookie)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        token = _incoming_refresh(request)
        if not token:
            return Response({'message': 'Not signed in.'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            refresh = RefreshToken(token)
            user = User.objects.get(pk=refresh['user_id'], is_active=True)
            refresh.blacklist()
        except (TokenError, User.DoesNotExist, KeyError):
            response = Response({'message': 'Your session has expired.'}, status=status.HTTP_401_UNAUTHORIZED)
            clear_refresh_cookie(response)
            return response
        return session_response(user)


class LogoutView(APIView):
    """Blacklists the refresh token so it can no longer mint access tokens."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        token = _incoming_refresh(request)
        if token:
            try:
                RefreshToken(token).blacklist()
            except TokenError:
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response


class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        return UserSerializer if self.request.method == 'GET' else UserUpdateSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        # Sign out other devices; this one gets a fresh session.
        revoke_all_sessions(request.user)
        return session_response(request.user)


class PasswordResetRequestView(AuthThrottleMixin, APIView):
    """Always answers 204 so the endpoint can't be used to discover accounts."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data['email'], is_active=True).first()
        if user:
            send_password_reset_email(user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetConfirmView(AuthThrottleMixin, APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        user.set_password(serializer.validated_data['password'])
        # Following the emailed link proves the address belongs to the user.
        user.email_verified = True
        user.save(update_fields=['password', 'email_verified'])
        revoke_all_sessions(user)
        claim_guest_bookings(user)
        return Response({'message': 'Password updated. You can now sign in.'})


class VerifyEmailView(AuthThrottleMixin, APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        user.email_verified = True
        user.save(update_fields=['email_verified'])
        claimed = claim_guest_bookings(user)
        return Response({'message': 'Email verified.', 'claimedBookings': claimed, 'user': UserSerializer(user).data})


class ResendVerificationView(AuthThrottleMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.email_verified:
            return Response({'message': 'Your email is already verified.'})
        issue_verification(request.user)
        return Response({'message': f'We sent a new link to {request.user.email}.'})
