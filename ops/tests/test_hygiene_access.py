from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from ops.hygiene import seed_lines
from ops.models import HygieneCheck, TaskOccurrence
from ops.scheduling import assign_organization_tasks
from organizations.models import Industry, Organization


class HygieneAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        industry = Industry.objects.create(code='pekara', name='Pekara')
        cls.org_a = Organization.objects.create(name='Pekara A', industry=industry)
        cls.org_b = Organization.objects.create(name='Pekara B', industry=industry)
        cls.staff_a = User.objects.create_user(
            username='radnik',
            password='test-pass',
            first_name='Mila',
            last_name='Radnik',
            organization=cls.org_a,
            role=User.Role.STAFF,
        )
        cls.owner_a = User.objects.create_user(
            username='vlasnik',
            password='test-pass',
            organization=cls.org_a,
            role=User.Role.OWNER,
        )
        cls.check = HygieneCheck.objects.create(
            organization=cls.org_a,
            work_date=timezone.localdate(),
            created_by=cls.staff_a,
        )
        seed_lines(cls.check)

    def test_task_records_actor_without_rewriting_it(self):
        assign_organization_tasks(self.org_a)
        self.client.force_login(self.staff_a)
        self.client.get(reverse('today'))
        occurrence = TaskOccurrence.objects.get(
            organization=self.org_a,
            organization_task__definition__code='t1',
            status=TaskOccurrence.Status.OPEN,
        )
        response = self.client.post(reverse('task_done', args=[occurrence.pk]), {'next': 'today'})
        self.assertEqual(response.status_code, 302)
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.done_by, self.staff_a)
        self.assertIsNotNone(occurrence.done_at)
        first_at = occurrence.done_at

        self.client.force_login(self.owner_a)
        again = self.client.post(reverse('task_done', args=[occurrence.pk]), {'next': 'tasks'})
        self.assertEqual(again.status_code, 302)
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.done_by, self.staff_a)
        self.assertEqual(occurrence.done_at, first_at)

    def test_hygiene_completion_records_actor_and_shows_it(self):
        self.client.force_login(self.staff_a)
        payload = {'action': 'complete', 'note': 'gotovo'}
        for line in self.check.lines.filter(is_required=True):
            payload[f'line_{line.pk}'] = 'on'
        response = self.client.post(
            reverse('hygiene_detail', args=[self.check.pk]),
            payload,
        )
        self.assertEqual(response.status_code, 302)
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, HygieneCheck.Status.DONE)
        self.assertEqual(self.check.completed_by, self.staff_a)
        self.assertIsNotNone(self.check.completed_at)
        done_lines = self.check.lines.filter(is_required=True)
        self.assertTrue(done_lines.exists())
        for line in done_lines:
            self.assertEqual(line.done_by, self.staff_a)
            self.assertIsNotNone(line.done_at)
        untouched = self.check.lines.filter(is_required=False).first()
        self.assertIsNone(untouched.done_by)

        detail = self.client.get(reverse('hygiene_detail', args=[self.check.pk]))
        self.assertContains(detail, 'Mila Radnik')
        history = self.client.get(reverse('hygiene_list'))
        self.assertContains(history, 'Mila Radnik')

    def test_other_organization_hygiene_is_not_found(self):
        foreign = HygieneCheck.objects.create(
            organization=self.org_b,
            work_date=timezone.localdate(),
            created_by=self.owner_a,
            note='tajna',
        )
        seed_lines(foreign)
        self.client.force_login(self.owner_a)
        detail = reverse('hygiene_detail', args=[foreign.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(
            self.client.post(detail, {'action': 'reopen', 'note': 'upad'}).status_code,
            404,
        )
        foreign.refresh_from_db()
        self.assertEqual(foreign.note, 'tajna')
        self.assertEqual(foreign.status, HygieneCheck.Status.OPEN)
