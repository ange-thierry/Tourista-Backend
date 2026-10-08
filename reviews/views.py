from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from bookings.services import booking_providers, notify
from bookings.views import paginate
from core.constants import BookingStatus, NotificationType, ServiceType
from core.utils import iso
from listings.models import Listing
from providers.services import get_or_seed_workspace

from .models import Review

REVIEWABLE_STATUSES = {BookingStatus.CHECKED_OUT, BookingStatus.COMPLETED}


def review_to_frontend(review: Review) -> dict:
    return {
        'id': review.id,
        'serviceType': review.service_type,
        'listingId': review.listing_id,
        'bookingId': review.booking_id,
        'serviceName': review.booking.service_name,
        'rating': review.rating,
        'title': review.title,
        'comment': review.comment,
        'authorName': review.user.name.split(' ')[0] + (
            f' {review.user.name.split(" ")[1][0]}.' if len(review.user.name.split(' ')) > 1 else ''
        ),
        'reply': review.reply or None,
        'repliedAt': iso(review.replied_at),
        'createdAt': iso(review.created_at),
    }


def refresh_listing_rating(service_type: str, listing_id: int) -> None:
    """Blend the catalog's original rating with published guest reviews."""
    listing = Listing.objects.filter(service_type=service_type, listing_id=listing_id).first()
    if not listing:
        return
    agg = Review.objects.filter(service_type=service_type, listing_id=listing_id, is_published=True).aggregate(
        n=Count('id'), total=Sum('rating')
    )
    n, total = agg['n'] or 0, agg['total'] or 0
    base_n = listing.base_reviews
    count = base_n + n
    if count:
        rating = (Decimal(listing.base_rating) * base_n + total) / count
        listing.rating = rating.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    listing.reviews = count
    listing.save(update_fields=['rating', 'reviews', 'updated_at'])


class CreateReviewSerializer(serializers.Serializer):
    bookingId = serializers.CharField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    title = serializers.CharField(max_length=120, allow_blank=True, required=False, default='')
    comment = serializers.CharField(max_length=3000)


class ReviewListCreateView(APIView):
    """GET public reviews for a listing; POST a review for one of your finished bookings."""

    def get_permissions(self):
        return [permissions.IsAuthenticated()] if self.request.method == 'POST' else [permissions.AllowAny()]

    def get(self, request):
        service_type = request.query_params.get('service_type')
        listing_id = request.query_params.get('listing_id', '')
        if service_type not in ServiceType.values or not listing_id.isdigit():
            raise ValidationError({'message': 'service_type and listing_id are required.'})
        qs = Review.objects.filter(
            service_type=service_type, listing_id=int(listing_id), is_published=True
        ).select_related('user', 'booking')
        summary = qs.aggregate(average=Avg('rating'), count=Count('id'))
        response = paginate(request, qs, review_to_frontend)
        listing = Listing.objects.filter(service_type=service_type, listing_id=int(listing_id)).first()
        payload = response.data if isinstance(response.data, dict) else {'results': response.data}
        payload['summary'] = {
            'guestReviews': summary['count'] or 0,
            'guestAverage': round(float(summary['average']), 1) if summary['average'] else None,
            'rating': float(listing.rating) if listing else None,
            'reviews': listing.reviews if listing else None,
        }
        return Response(payload)

    @transaction.atomic
    def post(self, request):
        serializer = CreateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        booking = get_object_or_404(Booking, pk=v['bookingId'], is_archived=False)
        if booking.user_id != request.user.pk:
            raise PermissionDenied('You can only review your own bookings.')
        if booking.status not in REVIEWABLE_STATUSES:
            raise ValidationError({'bookingId': 'You can review after your stay or visit is finished.'})
        if hasattr(booking, 'review'):
            raise ValidationError({'bookingId': 'You already reviewed this booking.'})
        if booking.listing_id is None:
            raise ValidationError({'bookingId': 'This booking is not linked to a listing.'})
        review = Review.objects.create(
            user=request.user,
            booking=booking,
            service_type=booking.service_type,
            listing_id=booking.listing_id,
            rating=v['rating'],
            title=v.get('title', '').strip(),
            comment=v['comment'].strip(),
        )
        refresh_listing_rating(review.service_type, review.listing_id)
        for provider in booking_providers(booking):
            notify(provider, title=f'New {review.rating}★ review',
                   message=f'{request.user.name} reviewed {booking.service_name}.',
                   type=NotificationType.SYSTEM, booking=booking)
        return Response(review_to_frontend(review), status=status.HTTP_201_CREATED)


class MyReviewsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Review.objects.filter(user=request.user).select_related('user', 'booking')
        return Response([review_to_frontend(r) for r in qs])


class ProviderReviewsView(APIView):
    """Reviews for the signed-in provider's linked listing."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.is_provider:
            raise PermissionDenied('Only providers have a reviews inbox.')
        ws = get_or_seed_workspace(request.user)
        qs = Review.objects.filter(
            service_type=ws.service_type, listing_id=ws.linked_listing_id, is_published=True
        ).select_related('user', 'booking')
        agg = qs.aggregate(average=Avg('rating'), count=Count('id'))
        distribution = {str(star): 0 for star in range(1, 6)}
        for row in qs.values('rating').annotate(n=Count('id')):
            distribution[str(row['rating'])] = row['n']
        listing = Listing.objects.filter(service_type=ws.service_type, listing_id=ws.linked_listing_id).first()
        return Response({
            'summary': {
                'guestReviews': agg['count'] or 0,
                'guestAverage': round(float(agg['average']), 1) if agg['average'] else None,
                'unanswered': qs.filter(reply='').count(),
                'distribution': distribution,
                'rating': float(listing.rating) if listing else None,
                'reviews': listing.reviews if listing else None,
            },
            'results': [review_to_frontend(r) for r in qs[:200]],
        })


class ReviewReplyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        review = get_object_or_404(Review.objects.select_related('booking', 'user'), pk=pk)
        allowed = request.user.is_platform_admin
        if request.user.is_provider:
            ws = get_or_seed_workspace(request.user)
            allowed = allowed or (ws.service_type == review.service_type and ws.linked_listing_id == review.listing_id)
        if not allowed:
            raise PermissionDenied('Only the listing manager can reply.')
        reply = str(request.data.get('reply', '')).strip()
        if not reply:
            raise ValidationError({'reply': 'Write a reply first.'})
        review.reply = reply[:3000]
        review.replied_at = timezone.now()
        review.save(update_fields=['reply', 'replied_at'])
        notify(review.user, title='The provider replied to your review',
               message=f'{review.booking.service_name}: "{reply[:120]}"',
               type=NotificationType.SYSTEM, booking=review.booking)
        return Response(review_to_frontend(review))


class ReviewDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        review = get_object_or_404(Review, pk=pk)
        if review.user_id != request.user.pk and not request.user.is_platform_admin:
            raise PermissionDenied('You cannot remove this review.')
        review.is_published = False
        review.save(update_fields=['is_published'])
        refresh_listing_rating(review.service_type, review.listing_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
