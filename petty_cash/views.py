"""Permission-controlled petty-cash cashbook views."""

from django.contrib import messages
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from horilla.decorators import login_required, permission_required

from petty_cash.forms import PettyCashAccountForm, PettyCashEntryForm, PettyCashVoidForm
from petty_cash.models import PettyCashAccount, PettyCashEntry


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _modal_success(request):
    """Reload the cashbook after a modal save so balances and the ledger agree."""
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("petty-cash-cashbook")
    return response


@login_required
@permission_required("petty_cash.view_pettycashaccount")
def cashbook(request):
    accounts = list(PettyCashAccount.objects.select_related("custodian").all())
    for account in accounts:
        account.balance = account.current_balance
    entries = PettyCashEntry.objects.select_related("account", "voided_by").all()
    account_id = request.GET.get("account", "")
    if account_id.isdigit():
        entries = entries.filter(account_id=account_id)
    status = request.GET.get("status", "")
    if status:
        entries = entries.filter(status=status)
    query = request.GET.get("search", request.GET.get("q", "")).strip()
    if query:
        from django.db.models import Q

        entries = entries.filter(
            Q(description__icontains=query)
            | Q(category__icontains=query)
            | Q(payee__icontains=query)
            | Q(reference__icontains=query)
            | Q(account__name__icontains=query)
        )
    # Do not blend currencies: a cash-out total only has meaning within its
    # own currency. Voided movements are audit records, not money spent.
    spending_totals = list(
        entries.filter(
            status=PettyCashEntry.STATUS_POSTED,
            direction=PettyCashEntry.DIRECTION_OUT,
        )
        .values("account__currency")
        .annotate(amount_spent=Sum("amount"))
        .order_by("account__currency")
    )
    cash_in_totals = list(
        entries.filter(
            status=PettyCashEntry.STATUS_POSTED,
            direction=PettyCashEntry.DIRECTION_IN,
        )
        .values("account__currency")
        .annotate(amount_received=Sum("amount"))
        .order_by("account__currency")
    )
    context = {
        "accounts": accounts,
        "entries": entries[:100],
        "selected_account": str(account_id),
        "selected_status": status,
        "query": query,
        "spending_totals": spending_totals,
        "cash_in_totals": cash_in_totals,
        "nav_title": _("Petty Cash"),
        "search_url": reverse("petty-cash-cashbook"),
        "search_swap_target": "#pettyCashbookContent",
        "search_input_attrs": format_html('value="{}"', query),
        "filter_body_template": "petty_cash/filter.html",
        "modern_filter": True,
        "create_attrs": format_html(
            'role="button" tabindex="0" data-toggle="oh-modal-toggle" data-target="#objectCreateModal" hx-get="{}" hx-target="#objectCreateModalTarget"',
            reverse("petty-cash-entry-create"),
        ) if request.user.has_perm("petty_cash.add_pettycashentry") else "",
    }
    if _is_htmx(request) and request.headers.get("HX-Sidebar-Nav") != "true":
        return render(request, "petty_cash/cashbook_content.html", context)
    return render(request, "petty_cash/cashbook.html", context)


@login_required
@permission_required("petty_cash.add_pettycashaccount")
def account_create(request):
    form = PettyCashAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Petty cash float created."))
        if _is_htmx(request):
            return _modal_success(request)
        return redirect("petty-cash-cashbook")
    return render(request, "petty_cash/entry_form_modal.html" if _is_htmx(request) else "petty_cash/account_form.html", {"form": form, "title": _("Create petty cash float"), "modal_target": "objectCreateModalTarget"})


@login_required
@permission_required("petty_cash.change_pettycashaccount")
def account_edit(request, account_id):
    account = get_object_or_404(PettyCashAccount.objects.all(), pk=account_id)
    form = PettyCashAccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Petty cash float updated."))
        if _is_htmx(request):
            return _modal_success(request)
        return redirect("petty-cash-cashbook")
    return render(request, "petty_cash/entry_form_modal.html" if _is_htmx(request) else "petty_cash/account_form.html", {"form": form, "account": account, "title": _("Edit petty cash float"), "modal_target": "objectUpdateModalTarget"})


@login_required
@permission_required("petty_cash.add_pettycashentry")
def entry_create(request):
    initial = {}
    account_id = request.GET.get("account")
    if account_id:
        initial["account"] = account_id
    form = PettyCashEntryForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Petty cash entry recorded."))
        if _is_htmx(request):
            return _modal_success(request)
        return redirect("petty-cash-cashbook")
    context = {"form": form, "title": _("Record petty cash entry"), "modal_target": "objectCreateModalTarget"}
    template = "petty_cash/entry_form_modal.html" if _is_htmx(request) else "petty_cash/entry_form.html"
    return render(request, template, context)


@login_required
@permission_required("petty_cash.change_pettycashentry")
def entry_edit(request, entry_id):
    entry = get_object_or_404(PettyCashEntry.objects.select_related("account"), pk=entry_id)
    if entry.status == PettyCashEntry.STATUS_VOID:
        messages.error(request, _("A voided entry cannot be edited."))
        return _modal_success(request) if _is_htmx(request) else redirect("petty-cash-cashbook")
    form = PettyCashEntryForm(request.POST or None, request.FILES or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Petty cash entry updated."))
        if _is_htmx(request):
            return _modal_success(request)
        return redirect("petty-cash-cashbook")
    context = {
        "form": form,
        "entry": entry,
        "title": _("Edit petty cash entry"),
        "modal_target": "objectUpdateModalTarget",
    }
    template = "petty_cash/entry_form_modal.html" if _is_htmx(request) else "petty_cash/entry_form.html"
    return render(request, template, context)


@login_required
@permission_required("petty_cash.change_pettycashentry")
def entry_void(request, entry_id):
    entry = get_object_or_404(PettyCashEntry.objects.all(), pk=entry_id)
    if entry.status == PettyCashEntry.STATUS_VOID:
        messages.info(request, _("This entry is already void."))
        return _modal_success(request) if _is_htmx(request) else redirect("petty-cash-cashbook")
    form = PettyCashVoidForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        entry.status = PettyCashEntry.STATUS_VOID
        entry.void_reason = form.cleaned_data["void_reason"]
        entry.voided_at = timezone.now()
        entry.voided_by = request.user
        entry.save(update_fields=["status", "void_reason", "voided_at", "voided_by", "modified_by"])
        messages.success(request, _("Petty cash entry voided. It remains in the cashbook audit trail."))
        return _modal_success(request) if _is_htmx(request) else redirect("petty-cash-cashbook")
    return render(request, "petty_cash/entry_form_modal.html" if _is_htmx(request) else "petty_cash/void_form.html", {
        "form": form, "entry": entry, "title": _("Void petty cash entry"),
        "modal_target": "objectUpdateModalTarget", "is_void": True,
    })


@login_required
@permission_required("petty_cash.view_pettycashentry")
def receipt_download(request, entry_id):
    entry = get_object_or_404(PettyCashEntry.objects.all(), pk=entry_id)
    if not entry.receipt:
        raise Http404
    return FileResponse(
        entry.receipt.open("rb"),
        as_attachment=True,
        filename=entry.receipt.name.rsplit("/", 1)[-1],
    )
