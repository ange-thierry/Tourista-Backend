from django.urls import path

from . import views

urlpatterns = [
    path('bookings/', views.BookingListCreateView.as_view(), name='booking-list'),
    path('bookings/quote/', views.BookingQuoteView.as_view(), name='booking-quote'),
    path('bookings/lookup/', views.BookingLookupView.as_view(), name='booking-lookup'),
    path('bookings/occupancy/', views.OccupancyView.as_view(), name='booking-occupancy'),
    path('bookings/stats/', views.BookingStatsView.as_view(), name='booking-stats'),
    path('bookings/export.csv', views.BookingExportView.as_view(), name='booking-export'),
    path('bookings/<str:pk>/', views.BookingDetailView.as_view(), name='booking-detail'),
    path('bookings/<str:pk>/status/', views.BookingStatusView.as_view(), name='booking-status'),
    path('bookings/<str:pk>/pay-balance/', views.BookingPayBalanceView.as_view(), name='booking-pay-balance'),
    path('bookings/<str:pk>/fulfillment/', views.BookingFulfillmentView.as_view(), name='booking-fulfillment'),
    path('bookings/<str:pk>/restore/', views.BookingRestoreView.as_view(), name='booking-restore'),
    path('availability/', views.AvailabilityView.as_view(), name='availability'),
    path('notifications/', views.NotificationListView.as_view(), name='notification-list'),
    path('notifications/read-all/', views.NotificationReadAllView.as_view(), name='notification-read-all'),
    path('notifications/<str:pk>/read/', views.NotificationReadView.as_view(), name='notification-read'),
]
