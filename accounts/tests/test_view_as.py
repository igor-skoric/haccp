from django.test import TestCase
from django.urls import reverse

from accounts.impersonation import VIEW_AS_SESSION_KEY
from accounts.models import User
from organizations.models import Industry, Organization, OrganizationSettings


class PlatformViewAsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        industry = Industry.objects.create(code='test-view-as', name='Pekara')
        cls.org_a = Organization.objects.create(name='Alfa View', industry=industry)
        cls.org_b = Organization.objects.create(name='Beta View', industry=industry)
        OrganizationSettings.objects.create(organization=cls.org_a)
        OrganizationSettings.objects.create(organization=cls.org_b)
        cls.owner_a = User.objects.create_user(
            username='view-owner-a',
            password='test-pass',
            first_name='Ana',
            last_name='Vlasnik',
            organization=cls.org_a,
            role=User.Role.OWNER,
        )
        cls.staff_a = User.objects.create_user(
            username='view-staff-a',
            password='test-pass',
            first_name='Mila',
            last_name='Radnik',
            organization=cls.org_a,
            role=User.Role.STAFF,
        )
        cls.owner_b = User.objects.create_user(
            username='view-owner-b',
            password='test-pass',
            organization=cls.org_b,
            role=User.Role.OWNER,
        )
        cls.admin = User.objects.create_user(
            username='view-platform',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )
        cls.admin_other = User.objects.create_user(
            username='view-platform-2',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )

    def test_admin_sees_clients_list_members_forbidden(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('platform_clients'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.org_a.name)
        self.assertContains(response, self.org_b.name)

        self.client.force_login(self.owner_a)
        self.assertEqual(self.client.get(reverse('platform_clients')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('platform_client_detail', args=[self.org_a.pk])).status_code,
            403,
        )

    def test_client_detail_lists_only_that_org_members(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('platform_client_detail', args=[self.org_a.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.owner_a.username)
        self.assertContains(response, self.staff_a.username)
        self.assertNotContains(response, self.owner_b.username)
        self.assertContains(response, 'View as user')

    def test_view_as_staff_matches_staff_permissions(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('view_as_start', args=[self.staff_a.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[VIEW_AS_SESSION_KEY], self.staff_a.pk)

        today = self.client.get(reverse('today'))
        self.assertEqual(today.status_code, 200)
        self.assertContains(today, 'Pregled kao')
        self.assertContains(today, 'Mila Radnik')
        self.assertEqual(self.client.get(reverse('settings_config')).status_code, 403)

        settings_page = self.client.get(reverse('settings'))
        self.assertEqual(settings_page.status_code, 200)
        self.assertNotContains(settings_page, 'Konfiguracija')

    def test_view_as_owner_can_configure(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(reverse('view_as_start', args=[self.owner_a.pk])).status_code,
            302,
        )
        self.assertEqual(self.client.get(reverse('today')).status_code, 200)
        self.assertEqual(self.client.get(reverse('settings_config')).status_code, 200)

    def test_cannot_view_as_other_platform_admin(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(reverse('view_as_start', args=[self.admin_other.pk])).status_code,
            403,
        )
        self.assertNotIn(VIEW_AS_SESSION_KEY, self.client.session)

    def test_member_cannot_start_view_as(self):
        self.client.force_login(self.owner_a)
        self.assertEqual(
            self.client.post(reverse('view_as_start', args=[self.staff_a.pk])).status_code,
            403,
        )

    def test_stop_returns_to_client_detail(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('view_as_start', args=[self.staff_a.pk]))
        response = self.client.post(reverse('view_as_stop'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse('platform_client_detail', args=[self.org_a.pk]),
        )
        self.assertNotIn(VIEW_AS_SESSION_KEY, self.client.session)

        clients = self.client.get(reverse('platform_clients'))
        self.assertEqual(clients.status_code, 200)
        self.assertNotContains(clients, 'Pregled kao')
        self.assertEqual(self.client.get(reverse('today')).status_code, 403)

    def test_home_and_login_redirect_platform_admin_to_clients(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('platform_clients'))

        self.client.logout()
        response = self.client.post(reverse('login'), {
            'username': 'view-platform',
            'password': 'test-pass',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('platform_clients'))

    def test_hub_forbidden_while_impersonating(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('view_as_start', args=[self.staff_a.pk]))
        self.assertEqual(self.client.get(reverse('platform_clients')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('platform_client_detail', args=[self.org_a.pk])).status_code,
            403,
        )
