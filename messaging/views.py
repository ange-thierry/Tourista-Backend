from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from bookings.services import notify
from core.constants import NotificationType, ServiceType
from core.utils import iso
from providers.models import ProviderWorkspace

from .models import Conversation, Message


def _side(user, convo: Conversation) -> str:
    if convo.guest_id == user.pk:
        return 'guest'
    if convo.workspace.user_id == user.pk or user.is_platform_admin:
        return 'provider'
    raise PermissionDenied('This conversation is not yours.')


def _unread(convo: Conversation, side: str) -> int:
    last_read = convo.guest_last_read_at if side == 'guest' else convo.provider_last_read_at
    other = convo.messages.exclude(sender=convo.guest) if side == 'guest' else convo.messages.filter(sender=convo.guest)
    return other.filter(created_at__gt=last_read).count() if last_read else other.count()


def conversation_to_frontend(convo: Conversation, user) -> dict:
    side = _side(user, convo)
    last = convo.messages.order_by('-created_at').first()
    return {
        'id': convo.id,
        'subject': convo.subject,
        'role': side,
        'companyName': convo.workspace.company_name,
        'serviceType': convo.workspace.service_type,
        'listingId': convo.workspace.linked_listing_id,
        'guestName': convo.guest.name,
        'guestEmail': convo.guest.email if side == 'provider' else None,
        'bookingId': convo.booking_id,
        'bookingReference': convo.booking.reference if convo.booking_id else None,
        'lastMessage': last.body[:160] if last else '',
        'lastMessageAt': iso(last.created_at) if last else iso(convo.created_at),
        'unread': _unread(convo, side),
    }


def message_to_frontend(msg: Message, user) -> dict:
    return {
        'id': msg.id,
        'body': msg.body,
        'senderName': msg.sender.name,
        'mine': msg.sender_id == user.pk,
        'createdAt': iso(msg.created_at),
    }


class StartConversationSerializer(serializers.Serializer):
    bookingId = serializers.CharField(required=False, allow_blank=True)
    serviceType = serializers.ChoiceField(choices=ServiceType.choices, required=False)
    listingId = serializers.IntegerField(required=False)
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True)
    message = serializers.CharField(max_length=4000)


def _notify_other(convo: Conversation, sender, body: str) -> None:
    recipient = convo.workspace.user if sender.pk == convo.guest_id else convo.guest
    notify(recipient, title=f'New message from {sender.name}', message=f'{convo.subject}: {body[:140]}',
           type=NotificationType.SYSTEM, booking=convo.booking)


class ConversationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.is_platform_admin:
            qs = Conversation.objects.all()
        else:
            qs = Conversation.objects.filter(Q(guest=user) | Q(workspace__user=user))
        qs = qs.select_related('workspace', 'guest', 'booking')[:200]
        return Response([conversation_to_frontend(c, user) for c in qs])

    @transaction.atomic
    def post(self, request):
        """Start (or continue) a thread with the provider of a booking or listing."""
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        booking = None
        if v.get('bookingId'):
            booking = get_object_or_404(Booking, pk=v['bookingId'])
            if booking.user_id != request.user.pk:
                raise PermissionDenied('You can only message about your own bookings.')
            service_type, listing_id = booking.service_type, booking.listing_id
        else:
            service_type, listing_id = v.get('serviceType'), v.get('listingId')
            if not service_type or not listing_id:
                raise ValidationError({'message': 'Choose a booking or a company to message.'})
        workspace = ProviderWorkspace.objects.filter(
            service_type=service_type, linked_listing_id=listing_id, user__is_active=True
        ).first()
        if workspace is None:
            raise ValidationError({'message': "This company isn't on Tourista messaging yet. Use their phone number."})
        if workspace.user_id == request.user.pk:
            raise ValidationError({'message': 'You manage this listing.'})

        convo = Conversation.objects.filter(guest=request.user, workspace=workspace, booking=booking).first()
        if convo is None:
            subject = v.get('subject') or (
                f'Booking {booking.reference}' if booking else f'Question for {workspace.company_name}'
            )
            convo = Conversation.objects.create(
                guest=request.user, workspace=workspace, booking=booking, subject=subject[:200]
            )
        Message.objects.create(conversation=convo, sender=request.user, body=v['message'].strip())
        convo.guest_last_read_at = timezone.now()
        convo.save(update_fields=['guest_last_read_at', 'updated_at'])
        _notify_other(convo, request.user, v['message'])
        return Response(conversation_to_frontend(convo, request.user), status=status.HTTP_201_CREATED)


class MessageListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get(self, request, pk) -> tuple[Conversation, str]:
        convo = get_object_or_404(Conversation.objects.select_related('workspace', 'guest', 'booking'), pk=pk)
        return convo, _side(request.user, convo)

    def get(self, request, pk):
        convo, side = self._get(request, pk)
        field = 'guest_last_read_at' if side == 'guest' else 'provider_last_read_at'
        setattr(convo, field, timezone.now())
        Conversation.objects.filter(pk=convo.pk).update(**{field: getattr(convo, field)})
        return Response({
            'conversation': conversation_to_frontend(convo, request.user),
            'messages': [message_to_frontend(m, request.user) for m in convo.messages.select_related('sender')],
        })

    def post(self, request, pk):
        convo, side = self._get(request, pk)
        body = str(request.data.get('body', '')).strip()
        if not body:
            raise ValidationError({'body': 'Write a message first.'})
        msg = Message.objects.create(conversation=convo, sender=request.user, body=body[:4000])
        field = 'guest_last_read_at' if side == 'guest' else 'provider_last_read_at'
        setattr(convo, field, timezone.now())
        convo.save(update_fields=[field, 'updated_at'])
        _notify_other(convo, request.user, body)
        return Response(message_to_frontend(msg, request.user), status=status.HTTP_201_CREATED)
