from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AvailabilityRule, CatalogItem, ProviderWorkspace, StaffMember
from .serializers import (
    AvailabilityRuleSerializer,
    CatalogItemSerializer,
    ProfileSerializer,
    StaffSerializer,
    workspace_to_frontend,
)
from .services import get_or_seed_workspace, listing_taken


class IsProvider(permissions.BasePermission):
    message = 'Only service-provider accounts have a company workspace.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_provider)


def _fresh(ws: ProviderWorkspace) -> dict:
    ws.save(update_fields=['updated_at'])
    ws = ProviderWorkspace.objects.prefetch_related('catalog', 'availability').get(pk=ws.pk)
    return workspace_to_frontend(ws)


class WorkspaceView(APIView):
    """GET the signed-in provider's workspace (created with sample data on first access)."""

    permission_classes = [IsProvider]

    def get(self, request):
        ws = get_or_seed_workspace(request.user)
        ws = ProviderWorkspace.objects.prefetch_related('catalog', 'availability').get(pk=ws.pk)
        return Response(workspace_to_frontend(ws))


class WorkspaceProfileView(APIView):
    permission_classes = [IsProvider]

    def patch(self, request):
        ws = get_or_seed_workspace(request.user)
        serializer = ProfileSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        values = serializer.model_values()
        listing_id = values.get('linked_listing_id')
        if listing_id and listing_taken(ws.service_type, listing_id, ws):
            raise ValidationError({'linkedListingId': 'Another provider already manages this listing.'})
        for field, value in values.items():
            setattr(ws, field, value)
        ws.save()
        return Response(_fresh(ws))


class CatalogItemView(APIView):
    """PUT upserts the item with this id; DELETE removes it and its availability rules."""

    permission_classes = [IsProvider]

    def put(self, request, item_id):
        ws = get_or_seed_workspace(request.user)
        serializer = CatalogItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        existing = CatalogItem.objects.filter(pk=item_id).first()
        if existing and existing.workspace_id != ws.pk:
            raise ValidationError({'id': 'This id belongs to another catalog.'})
        values = serializer.model_values()
        if not existing:
            values['position'] = (ws.catalog.aggregate(m=Max('position'))['m'] or 0) + 1
        CatalogItem.objects.update_or_create(pk=item_id, workspace=ws, defaults=values)
        return Response(_fresh(ws))

    def delete(self, request, item_id):
        ws = get_or_seed_workspace(request.user)
        ws.catalog.filter(pk=item_id).delete()
        ws.availability.filter(item_id=item_id).delete()
        return Response(_fresh(ws))


class CatalogItemCreateView(APIView):
    """POST creates an item with a server-generated id."""

    permission_classes = [IsProvider]

    def post(self, request):
        ws = get_or_seed_workspace(request.user)
        serializer = CatalogItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.model_values()
        values['position'] = (ws.catalog.aggregate(m=Max('position'))['m'] or 0) + 1
        CatalogItem.objects.create(id=CatalogItem.new_id(), workspace=ws, **values)
        return Response(_fresh(ws), status=status.HTTP_201_CREATED)


class AvailabilityRuleView(APIView):
    permission_classes = [IsProvider]

    def put(self, request, rule_id):
        ws = get_or_seed_workspace(request.user)
        serializer = AvailabilityRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        existing = AvailabilityRule.objects.filter(pk=rule_id).first()
        if existing and existing.workspace_id != ws.pk:
            raise ValidationError({'id': 'This id belongs to another workspace.'})
        values = serializer.model_values()
        if not existing:
            values['position'] = (ws.availability.aggregate(m=Max('position'))['m'] or 0) + 1
        AvailabilityRule.objects.update_or_create(pk=rule_id, workspace=ws, defaults=values)
        return Response(_fresh(ws))

    def delete(self, request, rule_id):
        ws = get_or_seed_workspace(request.user)
        ws.availability.filter(pk=rule_id).delete()
        return Response(_fresh(ws))


class PublicWorkspacesView(APIView):
    """Provider overrides for public company pages: profile, active catalog and availability.

    Filter with `?service_type=hotel&listing_id=1`.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = ProviderWorkspace.objects.filter(user__is_active=True).prefetch_related('catalog', 'availability')
        if service_type := request.query_params.get('service_type'):
            qs = qs.filter(service_type=service_type)
        if (listing_id := request.query_params.get('listing_id', '')).isdigit():
            qs = qs.filter(linked_listing_id=int(listing_id))
        return Response([workspace_to_frontend(ws, public=True) for ws in qs])


class StaffListView(APIView):
    permission_classes = [IsProvider]

    def get(self, request):
        ws = get_or_seed_workspace(request.user)
        return Response(StaffSerializer(ws.staff.all(), many=True).data)

    def post(self, request):
        ws = get_or_seed_workspace(request.user)
        serializer = StaffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(workspace=ws)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class StaffDetailView(APIView):
    permission_classes = [IsProvider]

    def _get(self, request, pk):
        ws = get_or_seed_workspace(request.user)
        return get_object_or_404(StaffMember, pk=pk, workspace=ws)

    def patch(self, request, pk):
        serializer = StaffSerializer(self._get(request, pk), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        self._get(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
