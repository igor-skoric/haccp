from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.permissions import can_configure, can_manage_members, can_operate
from ops.models import HygieneCheck, TaskOccurrence
from ops.scheduling import assign_organization_tasks
from ops.hygiene import seed_lines
from organizations.models import Industry, Organization, OrganizationSettings


class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        industry = Industry.objects.create(code='test-kafic', name='Kafić')
        cls.org_a = Organization.objects.create(name='Alfa', industry=industry)
        cls.org_b = Organization.objects.create(name='Beta', industry=industry)
        OrganizationSettings.objects.create(
            organization=cls.org_a,
            temp_min_c=Decimal('2.0'),
            temp_max_c=Decimal('3.5'),
        )
        OrganizationSettings.objects.create(organization=cls.org_b)
        cls.owner_a = User.objects.create_user(
            username='vlasnik-a',
            password='test-pass',
            organization=cls.org_a,
            role=User.Role.OWNER,
        )
        cls.staff_a = User.objects.create_user(
            username='zaposleni-a',
            password='test-pass',
            first_name='Mila',
            last_name='Radnik',
            organization=cls.org_a,
            role=User.Role.STAFF,
        )
        cls.owner_b = User.objects.create_user(
            username='vlasnik-b',
            password='test-pass',
            organization=cls.org_b,
            role=User.Role.OWNER,
        )
        cls.admin = User.objects.create_user(
            username='platforma',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )
        cls.orphan = User.objects.create_user(
            username='bez-objekta',
            password='test-pass',
            role=User.Role.STAFF,
        )
        cls.check_a = HygieneCheck.objects.create(
            organization=cls.org_a,
            work_date='2026-10-16',
            created_by=cls.owner_a,
        )
        seed_lines(cls.check_a)
        cls.check_b = HygieneCheck.objects.create(
            organization=cls.org_b,
            work_date='2026-10-16',
            created_by=cls.owner_b,
            note='beta',
        )
        seed_lines(cls.check_b)

    def test_permission_helpers(self):
        self.assertTrue(can_operate(self.owner_a, self.org_a))
        self.assertTrue(can_operate(self.staff_a, self.org_a))
        self.assertFalse(can_operate(self.staff_a, self.org_b))
        self.assertFalse(can_operate(self.admin, None))
        self.assertTrue(can_operate(self.admin, self.org_a))
        self.assertTrue(can_configure(self.owner_a, self.org_a))
        self.assertFalse(can_configure(self.staff_a, self.org_a))
        self.assertFalse(can_configure(self.owner_a, self.org_b))
        self.assertFalse(can_configure(self.admin, None))
        self.assertTrue(can_configure(self.admin, self.org_a))
        self.assertTrue(can_manage_members(self.owner_a, self.org_a))
        self.assertFalse(can_manage_members(self.staff_a, self.org_a))
        self.assertEqual(
            can_manage_members(self.admin, self.org_a),
            can_configure(self.admin, self.org_a),
        )

    def test_staff_settings_page_hides_configuration(self):
        self.client.force_login(self.staff_a)
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Konfiguracija')
        self.assertContains(response, 'Dokumentacija')
        self.assertContains(response, 'Odjava')

    def test_owner_settings_page_shows_configuration(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'Konfiguracija')

    def test_staff_cannot_read_or_post_configuration(self):
        self.client.force_login(self.staff_a)
        self.assertEqual(self.client.get(reverse('settings_config')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('settings_section', args=['temperatura'])).status_code,
            403,
        )
        response = self.client.post(reverse('settings_section', args=['temperatura']), {
            'temp_min_c': '0.0',
            'temp_max_c': '7.0',
        })
        self.assertEqual(response.status_code, 403)
        self.org_a.settings.refresh_from_db()
        self.assertEqual(self.org_a.settings.temp_max_c, Decimal('3.5'))

    def test_owner_can_change_temperature_limits(self):
        self.client.force_login(self.owner_a)
        self.assertEqual(
            self.client.get(reverse('settings_section', args=['temperatura'])).status_code,
            200,
        )
        response = self.client.post(reverse('settings_section', args=['temperatura']), {
            'temp_min_c': '1.0',
            'temp_max_c': '9.0',
        })
        self.assertEqual(response.status_code, 302)
        self.org_a.settings.refresh_from_db()
        self.assertEqual(self.org_a.settings.temp_max_c, Decimal('9.0'))

    def test_staff_and_owner_can_open_operational_pages(self):
        for user in (self.staff_a, self.owner_a):
            self.client.force_login(user)
            for name in ('today', 'temperatures', 'alerts', 'tasks'):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200, name)

    def test_platform_admin_must_choose_an_organization(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('settings_config'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '3.5')
        self.assertNotIn('platform_org_id', self.client.session)
        self.assertEqual(
            self.client.get(reverse('hygiene_detail', args=[self.check_a.pk])).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse('today')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('settings_section', args=['temperatura']), {
                'temp_min_c': '0.0',
                'temp_max_c': '6.0',
            }).status_code,
            403,
        )
        self.org_a.settings.refresh_from_db()
        self.assertEqual(self.org_a.settings.temp_max_c, Decimal('3.5'))

        response = self.client.get(
            reverse('settings_config'),
            {'objekat': self.org_a.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['platform_org_id'], self.org_a.pk)
        self.assertContains(response, '3.5')
        self.assertEqual(
            self.client.get(reverse('hygiene_detail', args=[self.check_a.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse('hygiene_detail', args=[self.check_b.pk])).status_code,
            404,
        )
        self.assertEqual(self.client.get(reverse('temperatures')).status_code, 200)
        self.assertEqual(
            self.client.post(reverse('settings_section', args=['temperatura']), {
                'temp_min_c': '1.0',
                'temp_max_c': '6.0',
            }).status_code,
            302,
        )
        self.org_a.settings.refresh_from_db()
        self.org_b.settings.refresh_from_db()
        self.assertEqual(self.org_a.settings.temp_max_c, Decimal('6.0'))
        self.assertEqual(self.org_b.settings.temp_max_c, Decimal('8.0'))

    def test_member_session_cannot_switch_tenant(self):
        self.client.force_login(self.staff_a)
        session = self.client.session
        session['platform_org_id'] = self.org_b.pk
        session.save()
        self.assertEqual(
            self.client.get(reverse('today'), {'objekat': self.org_b.pk}).status_code,
            200,
        )
        self.assertEqual(self.client.session['platform_org_id'], self.org_b.pk)
        self.assertEqual(
            self.client.get(reverse('hygiene_detail', args=[self.check_b.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse('hygiene_detail', args=[self.check_b.pk]),
                {'action': 'save', 'note': 'tudje'},
            ).status_code,
            404,
        )
        self.check_b.refresh_from_db()
        self.assertEqual(self.check_b.note, 'beta')
        assign_organization_tasks(self.org_a)
        self.client.get(reverse('today'))
        occurrence = TaskOccurrence.objects.get(
            organization=self.org_a,
            organization_task__definition__code='t1',
            status=TaskOccurrence.Status.OPEN,
        )
        self.assertEqual(
            self.client.post(reverse('task_done', args=[occurrence.pk]), {'next': 'today'}).status_code,
            302,
        )
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, TaskOccurrence.Status.DONE)
        self.assertEqual(occurrence.done_by, self.staff_a)
        self.assertFalse(
            TaskOccurrence.objects.filter(organization=self.org_b, status=TaskOccurrence.Status.DONE).exists()
        )

    def test_orphan_cannot_open_hygiene(self):
        self.client.force_login(self.orphan)
        detail = reverse('hygiene_detail', args=[self.check_a.pk])
        self.assertEqual(self.client.get(detail).status_code, 403)
        self.assertEqual(
            self.client.post(detail, {'action': 'save', 'note': 'bez'}).status_code,
            403,
        )
        self.check_a.refresh_from_db()
        self.assertEqual(self.check_a.note, '')
        self.assertEqual(self.check_a.status, HygieneCheck.Status.OPEN)
