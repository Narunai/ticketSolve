"""
URL configuration for ticket_system project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.templatetags.static import static

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=static('img/favicon.png'), permanent=True)),
    path('admin/', admin.site.urls),
    path('', include('tickets.urls')),
]
