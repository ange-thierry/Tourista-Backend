"""Platform-admin endpoints that power the in-app admin dashboard."""

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import UserSerializer
from bookings.models import Booking
from bookings.serializers import booking_to_frontend
from bookings.views import booking_stats, paginate
from core.utils import iso
from inquiries.models import ContactMessage, DemoRequest
from listings.models import Listing
from providers.models import ProviderWorkspace
from reviews.models import Review

from .constants import UserRole

User = get_user_model()


class IsPlatformAdmin(permissions.BasePermission):
    message = 'Administrator access required.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_platform_admin)


def contact_to_frontend(m: ContactMessage) -> dict:
    return {'id': m.id, 'kind': 'contact', 'name': m.name, 'email': m.email, 'subject': m.subject,
            'message': m.message, 'handled': m.handled, 'createdAt': iso(m.created_at)}


def demo_to_frontend(d: DemoRequest) -> dict:
    return {'id': d.id, 'kind': 'demo', 'name': d.full_name, 'email': d.email, 'phone': d.phone,
            'company': d.company, 'subject': f'Demo · {d.stakeholder_type or "general"}',
            'message': d.specific_needs or d.goals or d.additional_info,
            'preferredDate': d.preferred_date.isoformat(), 'preferredTime': d.preferred_time,
            'handled': d.handled, 'createdAt': iso(d.created_at)}


class AdminOverviewView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        bookings = Booking.objects.filter(is_archived=False)
        users_by_role = {row['role']: row['n'] for row in User.objects.values('role').annotate(n=Count('id'))}
        reviews = Review.objects.filter(is_published=True).aggregate(n=Count('id'), avg=Avg('rating'))
        providers = []
        for ws in ProviderWorkspace.objects.select_related('user').order_by('service_type'):
            scoped = bookings.filter(service_type=ws.service_type, listing_id=ws.linked_listing_id)
            providers.append({
                'companyName': ws.company_name,
                'email': ws.user.email,
                'role': ws.role,
                'serviceType': ws.service_type,
                'listingId': ws.linked_listing_id,
                'bookings': scoped.count(),
                'catalogItems': ws.catalog.count(),
            })
        return Response({
            'users': {
                'total': sum(users_by_role.values()),
                'byRole': users_by_role,
                'verified': User.objects.filter(email_verified=True).count(),
                'newThisMonth': User.objects.filter(
                    date_joined__gte=timezone.localdate().replace(day=1)
                ).count(),
            },
            'bookings': booking_stats(bookings),
            'listings': {row['service_type']: row['n'] for row in
                         Listing.objects.values('service_type').annotate(n=Count('id'))},
            'reviews': {'count': reviews['n'] or 0,
                        'average': round(float(reviews['avg']), 1) if reviews['avg'] else None},
            'inquiries': {
                'openContacts': ContactMessage.objects.filter(handled=False).count(),
                'openDemos': DemoRequest.objects.filter(handled=False).count(),
            },
            'recentBookings': [booking_to_frontend(b) for b in bookings.order_by('-created_at')[:8]],
            'providers': providers,
        })


class AdminUserListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = User.objects.all().order_by('-date_joined')
        if role := request.query_params.get('role'):
            qs = qs.filter(role=role)
        if search := request.query_params.get('search', '').strip():
            qs = qs.filter(Q(email__icontains=search) | Q(name__icontains=search))

        def serialize(user):
            data = UserSerializer(user).data
            data.update({'isActive': user.is_active, 'dateJoined': iso(user.date_joined),
                         'lastLogin': iso(user.last_login)})
            return data

        return paginate(request, qs, serialize)


class AdminUserDetailView(APIView):
    """PATCH `{isActive?, role?}`."""

    permission_classes = [IsPlatformAdmin]

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user.pk == request.user.pk:
            raise ValidationError({'message': 'You cannot change your own admin account here.'})
        fields = []
        if 'isActive' in request.data:
            user.is_active = bool(request.data['isActive'])
            fields.append('is_active')
        if 'role' in request.data:
            if request.data['role'] not in UserRole.values:
                raise ValidationError({'role': 'Unknown role.'})
            user.role = request.data['role']
            fields.append('role')
        if fields:
            user.save(update_fields=fields)
        data = UserSerializer(user).data
        data['isActive'] = user.is_active
        return Response(data)


class AdminInquiryListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        open_only = request.query_params.get('open') in ('1', 'true')
        contacts = ContactMessage.objects.all()
        demos = DemoRequest.objects.all()
        if open_only:
            contacts, demos = contacts.filter(handled=False), demos.filter(handled=False)
        items = [contact_to_frontend(m) for m in contacts[:100]] + [demo_to_frontend(d) for d in demos[:100]]
        items.sort(key=lambda item: item['createdAt'], reverse=True)
        return Response(items)


class AdminInquiryDetailView(APIView):
    permission_classes = [IsPlatformAdmin]

    def patch(self, request, kind, pk):
        model = ContactMessage if kind == 'contact' else DemoRequest if kind == 'demo' else None
        if model is None:
            raise ValidationError({'kind': 'Unknown inquiry type.'})
        obj = get_object_or_404(model, pk=pk)
        obj.handled = bool(request.data.get('handled', True))
        obj.save(update_fields=['handled'])
        return Response(contact_to_frontend(obj) if kind == 'contact' else demo_to_frontend(obj))
