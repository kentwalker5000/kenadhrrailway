from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
import math


class GeoFencing(models.Model):
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_in_meters = models.IntegerField()
    company_id = models.OneToOneField(
        "base.Company",
        related_name="geo_fencing",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    start = models.BooleanField(default=False)

    def clean(self):
        if self.company_id is None:
            qs = GeoFencing.objects.filter(company_id__isnull=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    _("Only one GeoFencing can have a null company_id.")
                )

        if self.latitude is None or not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValidationError({"latitude": _("Enter a valid latitude.")})
        if self.longitude is None or not math.isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValidationError({"longitude": _("Enter a valid longitude.")})
        if self.radius_in_meters is None or self.radius_in_meters <= 0:
            raise ValidationError({"radius_in_meters": _("Radius must be greater than zero.")})

        return super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()  # Run clean before save
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company_id"],
                name="unique_company_id_when_not_null_geofencing",
                condition=~Q(company_id=None),
            )
        ]
