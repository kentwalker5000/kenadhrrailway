"""Geofencing configuration can be saved without a network lookup."""

from django.test import TestCase

from geofencing.models import GeoFencing
from horilla.testkit import make_company


class GeoFencingSmokeTests(TestCase):
    def test_create_without_network_geocoder(self):
        company = make_company("Geo Co")
        geo = GeoFencing(
            latitude=12.97,
            longitude=77.59,
            radius_in_meters=100,
            company_id=company,
            start=False,
        )
        geo.save()
        self.assertIsNotNone(geo.pk)
        self.assertFalse(geo.start)
