from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from listings.discovery import SearchView, TripPlanView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
    path('api/auth/', include('accounts.urls')),
    path('api/listings/', include('listings.urls')),
    path('api/', include('bookings.urls')),
    path('api/provider/', include('providers.urls')),
    path('api/', include('inquiries.urls')),
    path('api/reviews/', include('reviews.urls')),
    path('api/conversations/', include('messaging.urls')),
    path('api/search/', SearchView.as_view(), name='search'),
    path('api/trip-plans/', TripPlanView.as_view(), name='trip-plans'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = 'Tourista Rwanda administration'
admin.site.site_title = 'Tourista Rwanda admin'
