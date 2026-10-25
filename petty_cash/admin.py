from django.contrib import admin

from petty_cash.models import PettyCashAccount, PettyCashEntry


@admin.register(PettyCashAccount)
class PettyCashAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "custodian", "opening_balance", "currency", "company_id", "is_active")
    list_filter = ("currency", "company_id", "is_active")
    search_fields = ("name", "custodian__employee_first_name", "custodian__employee_last_name")


@admin.register(PettyCashEntry)
class PettyCashEntryAdmin(admin.ModelAdmin):
    list_display = ("transaction_date", "account", "entry_type", "direction", "amount", "status", "company_id")
    list_filter = ("entry_type", "direction", "status", "company_id")
    search_fields = ("description", "payee", "reference", "category")
    readonly_fields = ("voided_at", "voided_by")
