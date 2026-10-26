from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from ops.models import ColdSpot, TemperatureReading
from ops.temperatures import ensure_cold_spots, open_alerts, record_temperature
from organizations.models import Industry, Organization, OrganizationSettings


class TemperatureFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        industry = Industry.objects.create(code='temp-test', name='Temp Test')
        cls.org = Organization.objects.create(name='Temp Org', industry=industry)
        OrganizationSettings.objects.create(
            organization=cls.org,
            temp_min_c=Decimal('2.0'),
            temp_max_c=Decimal('8.0'),
        )
        cls.owner = User.objects.create_user(
            username='temp-owner',
            password='test-pass',
            organization=cls.org,
            role=User.Role.OWNER,
        )
        cls.staff = User.objects.create_user(
            username='temp-staff',
            password='test-pass',
            organization=cls.org,
            role=User.Role.STAFF,
        )
        ensure_cold_spots(cls.org)

    def test_record_within_limits_and_show_on_page(self):
        spot = ColdSpot.objects.filter(organization=self.org).first()
        self.client.force_login(self.staff)
        response = self.client.post(reverse('temperatures'), {
            'cold_spot': spot.pk,
            'value_c': '5.0',
            'corrective_action': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TemperatureReading.objects.filter(organization=self.org).count(), 1)
        page = self.client.get(reverse('temperatures'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '5,0')

    def test_out_of_range_opens_alert_until_corrective(self):
        spot = ColdSpot.objects.filter(organization=self.org).first()
        self.client.force_login(self.staff)
        response = self.client.post(reverse('temperatures'), {
            'cold_spot': spot.pk,
            'value_c': '11.0',
            'corrective_action': '',
        })
        self.assertEqual(response.status_code, 302)
        reading = TemperatureReading.objects.get()
        self.assertFalse(reading.is_within_limits)
        self.assertTrue(reading.alert_open)

        alerts = [a for a in open_alerts(self.org) if a['open'] and a.get('reading_id') == reading.pk]
        self.assertEqual(len(alerts), 1)

        closed = self.client.post(reverse('temperature_corrective', args=[reading.pk]), {
            'corrective_action': 'Proizvodi prebačeni u drugu vitrinu',
            'next': 'alerts',
        })
        self.assertEqual(closed.status_code, 302)
        reading.refresh_from_db()
        self.assertFalse(reading.alert_open)

    def test_record_temperature_helper(self):
        spot = ColdSpot.objects.filter(organization=self.org).first()
        reading = record_temperature(self.org, self.owner, spot, Decimal('4.2'))
        self.assertTrue(reading.is_within_limits)
        self.assertEqual(reading.value_c, Decimal('4.2'))
