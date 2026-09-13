"""Use the same recovery policy on Django's account URLs and the login screen."""

from django.contrib.auth.urls import urlpatterns as django_auth_urls
from django.urls import path

from base import views

urlpatterns = [
    path("password_reset/", views.HorillaPasswordResetView.as_view(), name="password_reset"),
    path("password_reset/done/", views.reset_send_success, name="password_reset_done"),
    path("reset/<uidb64>/<token>/", views.KenadHrPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", views.KenadHrPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    *django_auth_urls,
]
