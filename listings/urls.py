from django.urls import path

from . import views

urlpatterns = [
    path('', views.listing_index, name='listing-index'),
    path('reference/', views.reference_data, name='listing-reference'),
    path('<str:service_type>/', views.listing_by_type, name='listing-by-type'),
    path('<str:service_type>/<int:listing_id>/', views.listing_detail, name='listing-detail'),
]
