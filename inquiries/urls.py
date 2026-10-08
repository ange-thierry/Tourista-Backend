from django.urls import path

from . import views

urlpatterns = [
    path('contact/', views.ContactView.as_view(), name='contact'),
    path('demo-requests/', views.DemoRequestView.as_view(), name='demo-request'),
]
