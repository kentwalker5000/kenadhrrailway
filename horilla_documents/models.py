import os
from datetime import date

from django.apps import apps
from django.db import models
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from django.forms import ValidationError
from django.urls import reverse_lazy
from django.utils.translation import gettext as _

from base.horilla_company_manager import HorillaCompanyManager
from base.models import Company
from employee.models import Employee
from horilla.models import HorillaModel, upload_path
from horilla_views.cbv_methods import render_template

STATUS = [
    ("requested", "Requested"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]
FORMATS = [
    ("any", "Any"),
    ("pdf", "PDF"),
    ("txt", "TXT"),
    ("docx", "DOCX"),
    ("xlsx", "XLSX"),
    ("jpg", "JPG"),
    ("png", "PNG"),
    ("jpeg", "JPEG"),
]

# HR library files are internal business records, not employee-submitted
# documents. Keep the allow-list deliberately narrow so an upload cannot be
# used to store executable or web content in the application media store.
HR_LIBRARY_ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".txt", ".jpg", ".jpeg", ".png",
}
HR_LIBRARY_MAX_SIZE_BYTES = 25 * 1024 * 1024


def document_create(instance):
    employees = instance.employee_id.all()
    for employee in employees:
        document = Document.objects.get_or_create(
            employee_id=employee,
            document_request_id=instance,
            defaults={"title": f"Upload {instance.title}"},
        )
        document[0].title = f"Upload {instance.title}"
        document[0].save()


class DocumentRequest(HorillaModel):
    title = models.CharField(max_length=100, verbose_name=_("Title"))
    employee_id = models.ManyToManyField(Employee, verbose_name=_("Employees"))
    format = models.CharField(choices=FORMATS, max_length=10, verbose_name=_("Format"))
    max_size = models.IntegerField(
        blank=True, null=True, verbose_name=_("Max size (In MB)")
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    objects = HorillaCompanyManager(
        related_company_field="employee_id__employee_work_info__company_id"
    )

    def get_edit_url(self):
        """
        Returns the edit url of the document request
        """

        return reverse_lazy("document-request-update", args=[self.pk])

    def get_delete_url(self):
        """
        Returns the delete url of the document request
        """

        return reverse_lazy("document-request-delete", args=[self.pk])

    class Meta:
        """
        Meta class to add additional options
        """

        verbose_name = _("Document Request")
        verbose_name_plural = _("Document Requests")

    def __str__(self):
        return self.title


@receiver(m2m_changed, sender=DocumentRequest.employee_id.through)
def document_request_m2m_changed(sender, instance, action, **kwargs):
    if action == "post_add":
        document_create(instance)

    elif action == "post_remove":
        document_create(instance)


class Document(HorillaModel):
    title = models.CharField(max_length=250)
    employee_id = models.ForeignKey(
        Employee, on_delete=models.PROTECT, verbose_name=_("Employee")
    )
    document_request_id = models.ForeignKey(
        DocumentRequest, on_delete=models.PROTECT, null=True
    )
    document = models.FileField(
        upload_to=upload_path, null=True, verbose_name=_("Document")
    )
    status = models.CharField(
        choices=STATUS, max_length=10, default="requested", verbose_name=_("Status")
    )
    reject_reason = models.TextField(
        blank=True, null=True, max_length=255, verbose_name=_("Rejection Reason")
    )
    issue_date = models.DateField(null=True, blank=True, verbose_name=_("Issue Date"))
    expiry_date = models.DateField(null=True, blank=True, verbose_name=_("Expiry Date"))
    notify_before = models.IntegerField(
        default=1, null=True, verbose_name=_("Notify Before")
    )
    is_digital_asset = models.BooleanField(
        default=False, verbose_name=_("Is Digital Asset")
    )
    objects = HorillaCompanyManager(
        related_company_field="employee_id__employee_work_info__company_id"
    )

    class Meta:
        """
        Meta class to add additional options
        """

        verbose_name = _("Document")
        verbose_name_plural = _("Documents")

    def __str__(self) -> str:
        return f"{self.title}"

    def clean(self, *args, **kwargs):
        super().clean(*args, **kwargs)
        file = self.document

        if len(self.title) < 3:
            raise ValidationError({"title": _("Title must be at least 3 characters")})

        if file and self.document_request_id:
            format = self.document_request_id.format
            max_size = self.document_request_id.max_size
            if max_size:
                if file.size > max_size * 1024 * 1024:
                    raise ValidationError(
                        {"document": _("File size exceeds the limit")}
                    )

            # Use the true final extension. A double extension such as
            # "file.pdf.html" must be rejected for a "pdf" request -- taking
            # an earlier segment (or splitext on the wrong part) would let an
            # HTML/script file through and enable stored XSS when served.
            # See GHSA-p68r-g665-5cm9.
            ext = os.path.splitext(file.name)[1].lstrip(".").lower()
            if format == "any":
                pass
            elif ext != format:
                raise ValidationError(
                    {"document": _("Please upload {} file only.").format(format)}
                )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_digital_asset:
            if apps.is_installed("asset"):
                from asset.models import Asset, AssetCategory

                asset_category = AssetCategory.objects.get_or_create(
                    asset_category_name="Digital Asset"
                )

                Asset.objects.create(
                    asset_name=self.title,
                    asset_purchase_date=date.today(),
                    asset_category_id=asset_category[0],
                    asset_status="Not-Available",
                    asset_purchase_cost=0,
                    expiry_date=self.expiry_date,
                    notify_before=self.notify_before,
                    asset_tracking_id=f"DIG_ID0{self.pk}",
                )

    def upload_documents_count(self):
        total_requests = Document.objects.filter(
            document_request_id=self.document_request_id
        )
        without_documents = total_requests.filter(document="").count()
        count = total_requests.count() - without_documents
        return count

    def document_title_display(self):
        """
        "Document" column text for the list view - title plus the employee it
        belongs to, matching the employee list's own "name" column pattern.
        """
        return f"{self.title} -- {self.employee_id.get_full_name()}"

    def document_status_display(self):
        """
        "Status" column text for the list view - a document without an
        uploaded file has no meaningful status yet.
        """
        if not self.document:
            return _("No Document")
        return self.get_status_display()

    def view_file_url(self):
        """
        URL used by the list view's row click to open the file preview modal.
        """
        return reverse_lazy("view-file", args=[self.id])

    def document_actions(self):
        """
        Upload/Approve/Reject/Delete column for the list view.
        """
        return render_template(
            path="cbv/documents/document_row_actions.html",
            context={"instance": self},
        )


class HRDocumentFolder(HorillaModel):
    """A company-scoped folder for HR-owned internal documents."""

    name = models.CharField(max_length=120, verbose_name=_("Folder name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    company_id = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("Company")
    )

    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company_id", "name"], name="unique_hr_document_folder_name"
            )
        ]
        verbose_name = _("HR document folder")
        verbose_name_plural = _("HR document folders")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # New folders inherit the selected tenant. Storing the tenant on both
        # folders and files lets the company manager scope direct file URLs too.
        if not self.pk and not self.company_id:
            from horilla import horilla_middlewares

            request = getattr(horilla_middlewares._thread_locals, "request", None)
            selected_company = request.session.get("selected_company") if request else None
            if selected_company and selected_company != "all":
                self.company_id = Company.find(selected_company)
        super().save(*args, **kwargs)


class HRLibraryDocument(HorillaModel):
    """An HR-owned file stored in an HR document folder, never an employee file."""

    folder = models.ForeignKey(
        HRDocumentFolder, on_delete=models.PROTECT, related_name="documents", verbose_name=_("Folder")
    )
    title = models.CharField(max_length=150, verbose_name=_("Title"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    document = models.FileField(upload_to=upload_path, verbose_name=_("Document"))
    company_id = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("Company")
    )

    objects = HorillaCompanyManager(related_company_field="company_id")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("HR library document")
        verbose_name_plural = _("HR library documents")

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if not self.document:
            return
        extension = os.path.splitext(self.document.name)[1].lower()
        if extension not in HR_LIBRARY_ALLOWED_EXTENSIONS:
            raise ValidationError(
                {"document": _("Upload a PDF, Office document, spreadsheet, text file, or image only.")}
            )
        if self.document.size > HR_LIBRARY_MAX_SIZE_BYTES:
            raise ValidationError({"document": _("Document size cannot exceed 25 MB.")})

    def save(self, *args, **kwargs):
        # A file always inherits its folder's company; forms cannot move a
        # document across tenants by submitting a different company value.
        if self.folder_id:
            self.company_id = self.folder.company_id
        super().save(*args, **kwargs)
