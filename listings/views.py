from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.constants import ServiceType

from .models import Listing, ReferenceData


def _filtered(request, service_type: str | None):
    qs = Listing.objects.filter(is_published=True)
    if service_type:
        if service_type not in ServiceType.values:
            raise NotFound(f'Unknown listing type "{service_type}".')
        qs = qs.filter(service_type=service_type)

    params = request.query_params
    if search := params.get('search', '').strip():
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(location__icontains=search)
            | Q(description__icontains=search)
            | Q(category__icontains=search)
        )
    if province := params.get('province', '').strip():
        qs = qs.filter(province__iexact=province)
    if category := params.get('category', '').strip():
        qs = qs.filter(category__iexact=category)
    if min_rating := params.get('min_rating'):
        try:
            qs = qs.filter(rating__gte=float(min_rating))
        except ValueError:
            pass
    return qs


@api_view(['GET'])
@permission_classes([AllowAny])
def listing_index(request):
    """All listings grouped by type: `{hotel: [...], park: [...], ...}`.

    Pass `?type=hotel` to get a flat array for one type instead.
    """
    service_type = request.query_params.get('type')
    qs = _filtered(request, service_type)
    if service_type:
        return Response([item.to_frontend() for item in qs])

    grouped: dict[str, list] = {value: [] for value in ServiceType.values}
    for item in qs:
        grouped[item.service_type].append(item.to_frontend())
    return Response(grouped)


@api_view(['GET'])
@permission_classes([AllowAny])
def listing_by_type(request, service_type: str):
    return Response([item.to_frontend() for item in _filtered(request, service_type)])


@api_view(['GET'])
@permission_classes([AllowAny])
def listing_detail(request, service_type: str, listing_id: int):
    item = get_object_or_404(
        Listing, service_type=service_type, listing_id=listing_id, is_published=True
    )
    return Response(item.to_frontend())


@api_view(['GET'])
@permission_classes([AllowAny])
def reference_data(request):
    """`{spaTreatmentsCatalog: [...], shopCategories: [...]}`."""
    return Response({row.key: row.data for row in ReferenceData.objects.all()})
