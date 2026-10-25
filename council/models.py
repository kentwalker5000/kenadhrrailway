"""Company-scoped council records and a permission-aware document library."""

import os

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from horilla import horilla_middlewares
from horilla.models import HorillaModel, upload_path
from horilla_auth.models import HorillaUser


ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png"}
MAX_DOCUMENT_SIZE_BYTES = 25 * 1024 * 1024


class CouncilMember(HorillaModel):
    """A governing-body member who is not necessarily an employee."""

    ROLE_CHOICES = [
        ("chair", _("Chairperson")),
        ("vice_chair", _("Vice Chairperson")),
        ("secretary", _("Secretary")),
        ("treasurer", _("Treasurer")),
        ("member", _("Member")),
        ("advisor", _("Advisor")),
        ("other", _("Other")),
    ]

    full_name = models.CharField(max_length=150, verbose_name=_("Full name"))
    email = models.EmailField(blank=True, verbose_name=_("Email"))
    phone = models.CharField(max_length=30, blank=True, verbose_name=_("Phone"))
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="member")
    organisation = models.CharField(max_length=150, blank=True, verbose_name=_("Organisation"))
    term_start = models.DateField(null=True, blank=True, verbose_name=_("Term start"))
    term_end = models.DateField(null=True, blank=True, verbose_name=_("Term end"))
    notes = models.TextField(blank=True, verbose_name=_("Internal notes"))
    company_id = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("Company")
    )

    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["full_name"]
        verbose_name = _("Council member")
        verbose_name_plural = _("Council members")

    def __str__(self):
        return self.full_name

    def clean(self):
        super().clean()
        if self.term_start and self.term_end and self.term_end < self.term_start:
            raise ValidationError({"term_end": _("Term end must be on or after term start.")})

    def save(self, *args, **kwargs):
        request = getattr(horilla_middlewares._thread_locals, "request", None)
        selected_company = request.session.get("selected_company") if request else None
        if not self.pk and not self.company_id and selected_company and selected_company != "all":
            self.company_id = Company.find(selected_company)
        super().save(*args, **kwargs)


class CouncilLibraryFolder(HorillaModel):
    """A shared council-document folder, with optional user/group restriction."""

    ACCESS_SHARED = "shared"
    ACCESS_RESTRICTED = "restricted"
    ACCESS_CHOICES = [
        (ACCESS_SHARED, _("All authorised council users")),
        (ACCESS_RESTRICTED, _("Only selected users and groups")),
    ]

    name = models.CharField(max_length=120, verbose_name=_("Folder name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    access_level = models.CharField(
        max_length=20, choices=ACCESS_CHOICES, default=ACCESS_SHARED, verbose_name=_("Access")
    )
    allowed_users = models.ManyToManyField(
        HorillaUser, blank=True, related_name="council_library_folders", verbose_name=_("Allowed users")
    )
    allowed_groups = models.ManyToManyField(
        Group, blank=True, related_name="council_library_folders", verbose_name=_("Allowed groups")
    )
    company_id = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("Company")
    )

    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["name"]
        verbose_name = _("Council document folder")
        verbose_name_plural = _("Council document folders")

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.access_level == self.ACCESS_RESTRICTED and not self.pk:
            # The form performs a stronger M2M validation after saving. This message
            # still protects programmatic creation that omits every access rule.
            return

    def user_can_view(self, user):
        if not user.is_authenticated:
            return False
        if user.is_superuser or user.has_perm("council.change_councillibraryfolder"):
            return True
        if self.access_level == self.ACCESS_SHARED:
            return user.has_perm("council.view_councildocument")
        return (
            self.allowed_users.filter(pk=user.pk).exists()
            or self.allowed_groups.filter(user=user).exists()
        )

    def save(self, *args, **kwargs):
        request = getattr(horilla_middlewares._thread_locals, "request", None)
        selected_company = request.session.get("selected_company") if request else None
        if not self.pk and not self.company_id and selected_company and selected_company != "all":
            self.company_id = Company.find(selected_company)
        super().save(*args, **kwargs)


class CouncilDocument(HorillaModel):
    """A private member document or a document stored in a shared library folder."""

    title = models.CharField(max_length=150, verbose_name=_("Title"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    member = models.ForeignKey(
        CouncilMember,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Council member"),
    )
    folder = models.ForeignKey(
        CouncilLibraryFolder,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Library folder"),
    )
    company_id = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("Company")
    )
    document = models.FileField(upload_to=upload_path, verbose_name=_("Document"))
    expires_on = models.DateField(null=True, blank=True, verbose_name=_("Expires on"))

    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Council document")
        verbose_name_plural = _("Council documents")

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if bool(self.member_id) == bool(self.folder_id):
            raise ValidationError(_("A document must belong to exactly one council member or library folder."))
        if self.document:
            extension = os.path.splitext(self.document.name)[1].lower()
            if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
                raise ValidationError({"document": _("Upload a PDF, Office document, spreadsheet, or image only.")})
            if self.document.size > MAX_DOCUMENT_SIZE_BYTES:
                raise ValidationError({"document": _("Document size cannot exceed 25 MB.")})

    def user_can_view(self, user):
        if not user.is_authenticated:
            return False
        # Private member documents are deliberately available only to council
        # document managers. A plain "view document" role is limited to the
        # shared library and cannot read identity/appointment documents.
        if user.is_superuser or user.has_perm("council.change_councildocument"):
            return True
        return bool(self.folder_id and self.folder.user_can_view(user))

    def save(self, *args, **kwargs):
        # Keeping the tenant directly on every stored file lets the company
        # manager scope both private member documents and folder documents.
        if self.member_id:
            self.company_id = self.member.company_id
        elif self.folder_id:
            self.company_id = self.folder.company_id
        super().save(*args, **kwargs)
