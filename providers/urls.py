from django.urls import path

from . import views

urlpatterns = [
    path('workspace/', views.WorkspaceView.as_view(), name='provider-workspace'),
    path('workspace/profile/', views.WorkspaceProfileView.as_view(), name='provider-profile'),
    path('catalog/', views.CatalogItemCreateView.as_view(), name='provider-catalog-create'),
    path('catalog/<str:item_id>/', views.CatalogItemView.as_view(), name='provider-catalog-item'),
    path('availability/<str:rule_id>/', views.AvailabilityRuleView.as_view(), name='provider-availability'),
    path('staff/', views.StaffListView.as_view(), name='provider-staff'),
    path('staff/<int:pk>/', views.StaffDetailView.as_view(), name='provider-staff-detail'),
    path('public-workspaces/', views.PublicWorkspacesView.as_view(), name='provider-public-workspaces'),
]
