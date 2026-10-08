from django.urls import path

from . import views

urlpatterns = [
    path('', views.ReviewListCreateView.as_view(), name='review-list'),
    path('mine/', views.MyReviewsView.as_view(), name='review-mine'),
    path('provider/', views.ProviderReviewsView.as_view(), name='review-provider'),
    path('<int:pk>/', views.ReviewDetailView.as_view(), name='review-detail'),
    path('<int:pk>/reply/', views.ReviewReplyView.as_view(), name='review-reply'),
]
