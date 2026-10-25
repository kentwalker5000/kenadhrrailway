from django.urls import path

from petty_cash import views


urlpatterns = [
    path("", views.cashbook, name="petty-cash-cashbook"),
    path("floats/new/", views.account_create, name="petty-cash-account-create"),
    path("floats/<int:account_id>/edit/", views.account_edit, name="petty-cash-account-edit"),
    path("entries/new/", views.entry_create, name="petty-cash-entry-create"),
    path("entries/<int:entry_id>/edit/", views.entry_edit, name="petty-cash-entry-edit"),
    path("entries/<int:entry_id>/void/", views.entry_void, name="petty-cash-entry-void"),
    path("entries/<int:entry_id>/receipt/", views.receipt_download, name="petty-cash-receipt-download"),
]
