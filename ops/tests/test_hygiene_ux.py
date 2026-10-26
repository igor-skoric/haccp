from datetime import date, datetime
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from ops.hygiene import required_progress_label, seed_lines, split_lines
from ops.models import HygieneCheck, HygieneLine, TaskOccurrence
from ops.scheduling import BELGRADE, assign_organization_tasks
from ops.task_board import load_task_board
from organizations.models import Industry, Organization

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=BELGRADE)
DAY = date(2026, 10, 23)


class HygieneUxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org = Organization.objects.create(
            name='Higijena UX A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.other = Organization.objects.create(
            name='Higijena UX B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.staff = User.objects.create_user(
            username='hig-ux-radnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.STAFF,
            first_name='Mila',
            last_name='Radnik',
        )
        self.other_staff = User.objects.create_user(
            username='hig-ux-drugi',
            password='test-pass',
            organization=self.other,
            role=User.Role.STAFF,
        )
        assign_organization_tasks(self.org, on_date=started)
        assign_organization_tasks(self.other, on_date=started)
        self.check = HygieneCheck.objects.create(
            organization=self.org,
            work_date=DAY,
            created_by=self.staff,
        )
        seed_lines(self.check)
        self.client.force_login(self.staff)

    def at_now(self):
        return patch('ops.task_board.timezone.now', return_value=NOW)

    def test_detail_separates_daily_and_periodic_sections(self):
        page = self.client.get(reverse('hygiene_detail', args=[self.check.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Svakodnevne kontrole')
        self.assertContains(page, 'Periodične kontrole')
        self.assertContains(page, 'nedeljno · mesečno')
        self.assertContains(page, 'hygiene-periodic')
        self.assertNotContains(page, '<details class="hygiene-periodic" open')

        daily, periodic = split_lines(self.check)
        self.assertEqual(len(daily), 5)
        self.assertEqual(len(periodic), 2)
        self.assertTrue(all(line.cadence == HygieneLine.Cadence.DAILY for line in daily))
        self.assertEqual(
            {line.cadence for line in periodic},
            {HygieneLine.Cadence.WEEKLY, HygieneLine.Cadence.MONTHLY},
        )
        for line in daily:
            self.assertContains(page, line.label)
        for line in periodic:
            self.assertContains(page, line.label)

    def test_progress_uses_required_daily_only(self):
        required = list(self.check.lines.filter(is_required=True))
        for line in required[:3]:
            line.is_done = True
            line.done_by = self.staff
            line.done_at = NOW
            line.save(update_fields=['is_done', 'done_by', 'done_at'])

        self.assertEqual(self.check.required_done_count, 3)
        self.assertEqual(self.check.required_total_count, 5)
        self.assertEqual(self.check.done_count, 3)
        self.assertEqual(self.check.total_count, 7)
        self.assertEqual(required_progress_label(self.check), '3 od 5 svakodnevnih kontrola')

        page = self.client.get(reverse('hygiene_detail', args=[self.check.pk]))
        self.assertContains(page, '3 od 5 svakodnevnih kontrola')
        self.assertNotContains(page, '3/7')
        self.assertNotContains(page, '3 od 7')

        with self.at_now():
            board = load_task_board(self.org, today=DAY, from_key='today')
            home = self.client.get(reverse('today'))
        self.assertEqual(board['hygiene_continue']['meta'], '3 od 5 svakodnevnih kontrola')
        self.assertContains(home, '3 od 5 svakodnevnih kontrola')
        self.assertNotContains(home, '/7 stavki')

        listing = self.client.get(reverse('hygiene_list'))
        self.assertContains(listing, '3/5 svakodnevnih')
        self.assertNotContains(listing, '3/7')

    def test_complete_still_requires_only_daily_sp(self):
        with self.at_now():
            self.client.get(reverse('today'))
        payload = {'action': 'complete', 'note': 'ok'}
        for line in self.check.lines.filter(is_required=True):
            payload[f'line_{line.pk}'] = 'on'
        response = self.client.post(reverse('hygiene_detail', args=[self.check.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, HygieneCheck.Status.DONE)
        periodic = self.check.lines.filter(is_required=False)
        self.assertEqual(periodic.count(), 2)
        self.assertFalse(periodic.filter(is_done=True).exists())
        occurrence = TaskOccurrence.objects.get(
            organization=self.org,
            organization_task__definition__record_key='hygiene',
            organization_task__definition__hygiene_line_code='',
            period_start__lte=DAY,
            period_end__gte=DAY,
        )
        self.assertEqual(occurrence.status, TaskOccurrence.Status.DONE)
        self.assertEqual(occurrence.hygiene_check_id, self.check.pk)

    def test_periodic_lines_can_still_be_marked(self):
        weekly = self.check.lines.get(cadence=HygieneLine.Cadence.WEEKLY)
        payload = {
            'action': 'save',
            'note': '',
            f'line_{weekly.pk}': 'on',
        }
        for line in self.check.lines.filter(is_required=True)[:2]:
            payload[f'line_{line.pk}'] = 'on'
        response = self.client.post(reverse('hygiene_detail', args=[self.check.pk]), payload)
        self.assertEqual(response.status_code, 302)
        weekly.refresh_from_db()
        self.assertTrue(weekly.is_done)
        self.assertEqual(weekly.done_by, self.staff)
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, HygieneCheck.Status.OPEN)
        self.assertEqual(self.check.lines.filter(is_done=True).count(), 3)

    def test_history_unchanged_and_org_isolation(self):
        snapshot = list(
            self.check.lines.order_by('pk').values_list(
                'pk', 'code', 'cadence', 'is_required', 'is_done',
            )
        )
        self.client.get(reverse('hygiene_detail', args=[self.check.pk]))
        after = list(
            self.check.lines.order_by('pk').values_list(
                'pk', 'code', 'cadence', 'is_required', 'is_done',
            )
        )
        self.assertEqual(snapshot, after)

        foreign = HygieneCheck.objects.create(
            organization=self.other,
            work_date=DAY,
            created_by=self.other_staff,
        )
        seed_lines(foreign)
        detail = reverse('hygiene_detail', args=[foreign.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(
            self.client.post(detail, {'action': 'save', 'note': 'x'}).status_code,
            404,
        )
        foreign.refresh_from_db()
        self.assertEqual(foreign.note, '')
