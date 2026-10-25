"""Company-scoped petty-cash floats and their immutable cashbook entries."""

import os
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case, DecimalField, F, Sum, When
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from employee.models import Employee
from horilla import horilla_middlewares
from horilla.models import HorillaModel, upload_path
from horilla_auth.models import HorillaUser


ALLOWED_RECEIPT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx"}
MAX_RECEIPT_SIZE_BYTES = 10 * 1024 * 1024


class PettyCashAccount(HorillaModel):
    """A physical petty-cash float held by a named custodian."""

    CURRENCY_CHOICES = [("GHS", "GHS"), ("USD", "USD"), ("GBP", "GBP")]

    name = models.CharField(max_length=120, verbose_name=_("Float name"))
    custodian = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="petty_cash_accounts",
        verbose_name=_("Cash custodian"),
    )
    opening_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name=_("Opening balance"),
    )
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="GHS")
    notes = models.TextField(blank=True, verbose_name=_("Notes"))
    company_id = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("Company")
    )

    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["name"]
        verbose_name = _("Petty cash float")
        verbose_name_plural = _("Petty cash floats")
        constraints = [
            models.UniqueConstraint(
                fields=("company_id", "name"), name="unique_petty_cash_float_name"
            )
        ]

    def __str__(self):
        return self.name

    @property
    def current_balance(self):
        """Opening float plus posted cash-in minus posted cash-out only."""
        delta = self.entries.filter(status=PettyCashEntry.STATUS_POSTED).aggregate(
            value=Coalesce(
                Sum(
                    Case(
                        When(direction=PettyCashEntry.DIRECTION_IN, then=F("amount")),
                        When(direction=PettyCashEntry.DIRECTION_OUT, then=-F("amount")),
                        default=Decimal("0.00"),
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    )
                ),
                Decimal("0.00"),
            )
        )["value"]
        return self.opening_balance + delta

    def save(self, *args, **kwargs):
        request = getattr(horilla_middlewares._thread_locals, "request", None)
        selected_company = request.session.get("selected_company") if request else None
        if not self.pk and not self.company_id and selected_company and selected_company != "all":
            self.company_id = Company.find(selected_company)
        super().save(*args, **kwargs)


class PettyCashEntry(HorillaModel):
    """One cashbook movement.  Entries are voided rather than deleted."""

    TYPE_TOP_UP = "top_up"
    TYPE_EXPENSE = "expense"
    TYPE_ADJUSTMENT = "adjustment"
    ENTRY_TYPE_CHOICES = [
        (TYPE_TOP_UP, _("Cash top-up")),
        (TYPE_EXPENSE, _("Expense")),
        (TYPE_ADJUSTMENT, _("Adjustment")),
    ]
    DIRECTION_IN = "in"
    DIRECTION_OUT = "out"
    DIRECTION_CHOICES = [(DIRECTION_IN, _("Cash in")), (DIRECTION_OUT, _("Cash out"))]
    STATUS_POSTED = "posted"
    STATUS_VOID = "void"
    STATUS_CHOICES = [(STATUS_POSTED, _("Posted")), (STATUS_VOID, _("Void"))]

    account = models.ForeignKey(
        PettyCashAccount, on_delete=models.PROTECT, related_name="entries", verbose_name=_("Cash float")
    )
    transaction_date = models.DateField(verbose_name=_("Transaction date"))
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES, default=TYPE_EXPENSE)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, default=DIRECTION_OUT)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    category = models.CharField(max_length=80, blank=True, verbose_name=_("Expense category"))
    payee = models.CharField(max_length=150, blank=True, verbose_name=_("Payee / source"))
    description = models.TextField(verbose_name=_("Purpose / description"))
    reference = models.CharField(max_length=80, blank=True, verbose_name=_("Receipt or reference number"))
    receipt = models.FileField(upload_to=upload_path, null=True, blank=True, verbose_name=_("Receipt attachment"))
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_POSTED)
    void_reason = models.CharField(max_length=250, blank=True, verbose_name=_("Void reason"))
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        HorillaUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="voided_petty_cash_entries",
    )
    company_id = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("Company")
    )

    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["-transaction_date", "-id"]
        verbose_name = _("Petty cash entry")
        verbose_name_plural = _("Petty cash entries")

    def __str__(self):
        return f"{self.account} — {self.transaction_date} — {self.amount}"

    def clean(self):
        super().clean()
        if self.entry_type == self.TYPE_TOP_UP:
            self.direction = self.DIRECTION_IN
        elif self.entry_type == self.TYPE_EXPENSE:
            self.direction = self.DIRECTION_OUT
        if self.account_id and self.company_id and self.account.company_id != self.company_id:
            raise ValidationError({"account": _("The cash float must belong to the same company.")})
        if self.receipt:
            extension = os.path.splitext(self.receipt.name)[1].lower()
            if extension not in ALLOWED_RECEIPT_EXTENSIONS:
                raise ValidationError({"receipt": _("Upload a PDF, Office file, spreadsheet, or image only.")})
            if self.receipt.size > MAX_RECEIPT_SIZE_BYTES:
                raise ValidationError({"receipt": _("Receipt attachments cannot exceed 10 MB.")})

    def save(self, *args, **kwargs):
        if self.account_id:
            self.company_id = self.account.company_id
        if self.entry_type == self.TYPE_TOP_UP:
            self.direction = self.DIRECTION_IN
        elif self.entry_type == self.TYPE_EXPENSE:
            self.direction = self.DIRECTION_OUT
        super().save(*args, **kwargs)
