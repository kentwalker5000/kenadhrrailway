"""Location checks shared by browser and API attendance endpoints."""
import math
from geopy.distance import geodesic
from .models import GeoFencing


def active_geofence(employee):
    company = employee.get_company() if employee else None
    return GeoFencing.objects.filter(company_id=company, start=True).first() if company else None


def check_location(employee, data):
    fence = active_geofence(employee)
    if not fence:
        return None
    try:
        lat, lon = float(data.get("latitude")), float(data.get("longitude"))
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError
        if not math.isfinite(fence.latitude) or not math.isfinite(fence.longitude) or fence.radius_in_meters <= 0:
            raise ValueError
        if geodesic((fence.latitude, fence.longitude), (lat, lon)).meters > fence.radius_in_meters:
            return "You are outside the permitted attendance area."
    except (TypeError, ValueError, OverflowError):
        return "A valid location is required for attendance. Please enable location access."
    return None
