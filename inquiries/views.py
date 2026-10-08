from django.db import transaction
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.emails import frontend_url, notify_staff

from .models import ContactMessage, DemoRequest


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'subject', 'message']


class DemoRequestSerializer(serializers.Serializer):
    """Accepts the camelCase payload of `DemoSchedulingModal`."""

    fullName = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=40, allow_blank=True, required=False, default='')
    company = serializers.CharField(max_length=200, allow_blank=True, required=False, default='')
    stakeholderType = serializers.CharField(max_length=40, allow_blank=True, required=False, default='')
    businessSize = serializers.CharField(max_length=100, allow_blank=True, required=False, default='')
    preferredDate = serializers.DateField()
    preferredTime = serializers.CharField(max_length=20)
    attendees = serializers.CharField(max_length=20, allow_blank=True, required=False, default='')
    specificNeeds = serializers.CharField(allow_blank=True, required=False, default='')
    currentChallenges = serializers.CharField(allow_blank=True, required=False, default='')
    goals = serializers.CharField(allow_blank=True, required=False, default='')
    additionalInfo = serializers.CharField(allow_blank=True, required=False, default='')

    def create(self, validated_data):
        v = validated_data
        return DemoRequest.objects.create(
            full_name=v['fullName'],
            email=v['email'],
            phone=v['phone'],
            company=v['company'],
            stakeholder_type=v['stakeholderType'],
            business_size=v['businessSize'],
            preferred_date=v['preferredDate'],
            preferred_time=v['preferredTime'],
            attendees=v['attendees'],
            specific_needs=v['specificNeeds'],
            current_challenges=v['currentChallenges'],
            goals=v['goals'],
            additional_info=v['additionalInfo'],
        )


class PublicFormView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'public_form'
    serializer_class: type[serializers.Serializer]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        subject, body = self.staff_alert(obj)
        transaction.on_commit(lambda: notify_staff(subject, body))
        return Response({'id': obj.pk, 'message': 'Received. Our team will be in touch within 24 hours.'},
                        status=status.HTTP_201_CREATED)


class ContactView(PublicFormView):
    serializer_class = ContactSerializer

    def staff_alert(self, m):
        body = (
            f'From {m.name} <{m.email}>\n\n{m.message}\n\n'
            f'Manage inquiries: {frontend_url("dashboard?tab=inquiries")}'
        )
        return f'New contact message: {m.subject or "(no subject)"}', body


class DemoRequestView(PublicFormView):
    serializer_class = DemoRequestSerializer

    def staff_alert(self, d):
        body = (
            f'{d.full_name} <{d.email}> {d.phone}\nCompany: {d.company or "-"}\n'
            f'Preferred: {d.preferred_date} {d.preferred_time}\n\n'
            f'Needs: {d.specific_needs}\nGoals: {d.goals}\nNotes: {d.additional_info}'
        )
        return f'Demo requested: {d.full_name} ({d.stakeholder_type or "general"})', body
