from django.utils.translation import gettext_lazy as _
import math
from rest_framework import serializers

from .models import GeoFencing


class GeoFencingSetupSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFencing
        fields = "__all__"

    def validate(self, data):
        latitude = data.get("latitude", getattr(self.instance, "latitude", None))
        longitude = data.get("longitude", getattr(self.instance, "longitude", None))
        radius = data.get("radius_in_meters", getattr(self.instance, "radius_in_meters", None))
        if latitude is None or not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise serializers.ValidationError({"latitude": _("Enter a valid latitude.")})
        if longitude is None or not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise serializers.ValidationError({"longitude": _("Enter a valid longitude.")})
        if radius is None or radius <= 0:
            raise serializers.ValidationError({"radius_in_meters": _("Radius must be greater than zero.")})
        return data


class EmployeeLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFencing
        fields = ["latitude", "longitude"]
