from django.urls import path

from . import admin_api, uploads, views

urlpatterns = [
    path('health/', views.health, name='health'),
    path('meta/', views.meta, name='meta'),
    path('uploads/', uploads.ImageUploadView.as_view(), name='upload-image'),
    path('admin/overview/', admin_api.AdminOverviewView.as_view(), name='admin-overview'),
    path('admin/users/', admin_api.AdminUserListView.as_view(), name='admin-users'),
    path('admin/users/<int:pk>/', admin_api.AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('admin/inquiries/', admin_api.AdminInquiryListView.as_view(), name='admin-inquiries'),
    path('admin/inquiries/<str:kind>/<int:pk>/', admin_api.AdminInquiryDetailView.as_view(),
         name='admin-inquiry-detail'),
]
