from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from ops.hygiene import seed_lines
from ops.models import GoodsReceipt, HygieneCheck, TaskOccurrence
from ops.receiving import create_goods_receipt
from ops.scheduling import BELGRADE, assign_organization_tasks
from ops.task_board import load_task_board
from organizations.models import Industry, Organization

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=BELGRADE)


class TodayUxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org = Organization.objects.create(
            name='UX Danas A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.other = Organization.objects.create(
            name='UX Danas B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.staff = User.objects.create_user(
            username='ux-danas-radnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.STAFF,
        )
        self.other_staff = User.objects.create_user(
            username='ux-danas-drugi',
            password='test-pass',
            organization=self.other,
            role=User.Role.STAFF,
        )
        assign_organization_tasks(self.org, on_date=started)
        assign_organization_tasks(self.other, on_date=started)
        self.client.force_login(self.staff)

    def at_now(self):
        return patch('ops.task_board.timezone.now', return_value=NOW)

    def test_home_one_receiving_card_with_dynamic_open_count(self):
        with self.at_now():
            r1 = create_goods_receipt(self.org, self.staff, received_on=NOW.date())
            r2 = create_goods_receipt(self.org, self.staff, received_on=NOW.date())
            r3 = create_goods_receipt(self.org, self.staff, received_on=date(2026, 10, 16))
            board = load_task_board(self.org, today=NOW.date(), from_key='today')

        self.assertEqual(board['counts']['open_receipts'], 3)
        self.assertEqual(len(board['open_receipts']), 3)
        self.assertFalse(any(row.get('receipt_pk') for row in board['in_progress']))
        self.assertFalse(any(row.get('record_key') == 'receiving' for row in board['for_today']))
        self.assertEqual(board['counts']['todo'], len(board['for_today']))
        self.assertEqual(board['counts']['in_progress'], len(board['in_progress']))
        self.assertNotIn(
            'Novi prijem',
            [row['title'] for row in board['for_today'] + board['in_progress']],
        )

        with self.at_now():
            home = self.client.get(reverse('today'))
        self.assertContains(home, 'Prijem sirovina', count=1)
        self.assertContains(home, '3 nezavršenih')
        self.assertContains(home, 'Novi prijem')
        self.assertContains(home, reverse('receiving_create'))
        self.assertContains(home, reverse('receiving_open'))
        self.assertNotContains(home, f'Prijem #{r1.pk}')
        self.assertNotContains(home, f'Prijem #{r2.pk}')
        self.assertNotContains(home, f'Prijem #{r3.pk}')
        self.assertNotContains(home, 'Brze akcije')
        self.assertContains(home, 'Otvoreni prijemi')
        self.assertEqual(home.context['open_receipts_count'], 3)

        open_page = self.client.get(f"{reverse('receiving_open')}?from=today")
        self.assertEqual(open_page.status_code, 200)
        self.assertEqual(open_page.context['back_url'], reverse('today'))
        self.assertContains(open_page, f'Prijem #{r1.pk}')
        self.assertContains(open_page, f'Prijem #{r2.pk}')
        self.assertContains(open_page, f'Prijem #{r3.pk}')
        self.assertContains(open_page, reverse('receiving_detail', args=[r1.pk]))

    def test_hygiene_continue_action_without_duplication(self):
        check = HygieneCheck.objects.create(
            organization=self.org,
            work_date=NOW.date(),
            created_by=self.staff,
        )
        seed_lines(check)
        with self.at_now():
            board = load_task_board(self.org, today=NOW.date(), from_key='today')
            home = self.client.get(reverse('today'))
        hygiene_today = [row for row in board['for_today'] if row.get('record_key') == 'hygiene']
        self.assertEqual(hygiene_today, [])
        self.assertIsNotNone(board['hygiene_continue'])
        self.assertEqual(board['hygiene_continue']['action_label'], 'Nastavi kontrolu')
        self.assertIn(f'/higijena/{check.pk}/', board['hygiene_continue']['href'])
        self.assertContains(home, 'Nastavi kontrolu')
        self.assertEqual(board['counts']['in_progress'], 1)

    def test_back_navigation_hygiene(self):
        check = HygieneCheck.objects.create(
            organization=self.org,
            work_date=NOW.date(),
            created_by=self.staff,
        )
        seed_lines(check)
        detail = reverse('hygiene_detail', args=[check.pk])

        from_today = self.client.get(f'{detail}?from=today')
        self.assertEqual(from_today.status_code, 200)
        self.assertEqual(from_today.context['back_url'], reverse('today'))

        from_tasks = self.client.get(f'{detail}?from=tasks')
        self.assertEqual(from_tasks.context['back_url'], reverse('tasks'))

        from_history = self.client.get(f'{detail}?from=hygiene_list')
        self.assertEqual(from_history.context['back_url'], reverse('hygiene_list'))
        self.assertEqual(from_history.context['history_url'], reverse('hygiene_list'))

        saved = self.client.post(f'{detail}?from=today', {
            'from': 'today',
            'action': 'save',
            'note': 'ok',
        })
        self.assertEqual(saved.status_code, 302)
        self.assertIn('from=today', saved.url)

    def test_back_navigation_receiving_and_open_list(self):
        with self.at_now():
            receipt = create_goods_receipt(self.org, self.staff, received_on=NOW.date())
        detail = reverse('receiving_detail', args=[receipt.pk])

        from_today = self.client.get(f'{detail}?from=today')
        self.assertEqual(from_today.context['back_url'], reverse('today'))
        from_tasks = self.client.get(f'{detail}?from=tasks')
        self.assertEqual(from_tasks.context['back_url'], reverse('tasks'))
        from_history = self.client.get(f'{detail}?from=receiving_list')
        self.assertEqual(from_history.context['back_url'], reverse('receiving_list'))
        from_open = self.client.get(f'{detail}?from=receiving_open')
        self.assertEqual(from_open.context['back_url'], reverse('receiving_open'))

        response = self.client.post(reverse('receiving_create'), {
            'next': 'today',
            'from': 'today',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('from=today', response.url)

        open_from_tasks = self.client.get(f"{reverse('receiving_open')}?from=tasks")
        self.assertEqual(open_from_tasks.context['back_url'], reverse('tasks'))

    def test_org_isolation_on_board(self):
        with self.at_now():
            create_goods_receipt(self.org, self.staff, received_on=NOW.date())
            create_goods_receipt(self.other, self.other_staff, received_on=NOW.date())
            board = load_task_board(self.org, today=NOW.date())
        receipt_ids = {row['receipt_pk'] for row in board['open_receipts']}
        foreign = GoodsReceipt.objects.get(organization=self.other)
        self.assertNotIn(foreign.pk, receipt_ids)
        self.assertEqual(board['counts']['open_receipts'], 1)

        open_page = self.client.get(reverse('receiving_open'))
        self.assertNotContains(open_page, f'Prijem #{foreign.pk}')

    def test_missed_preview_and_not_confirmable(self):
        with self.at_now():
            self.client.get(reverse('today'))
        yesterday = NOW.date() - timedelta(days=1)
        if self.org.tasks_started_on > yesterday:
            self.org.tasks_started_on = yesterday
            self.org.save(update_fields=['tasks_started_on'])
        from ops.models import OrganizationTask
        org_task = OrganizationTask.objects.get(organization=self.org, definition__code='t1')
        org_task.active_from = yesterday
        org_task.save(update_fields=['active_from'])
        window = org_task.activations.get(ended_on__isnull=True)
        if window.started_on > yesterday:
            window.started_on = yesterday
            window.save(update_fields=['started_on'])

        with self.at_now():
            home = self.client.get(reverse('today'))
            board = load_task_board(self.org, today=NOW.date())
        missed = [row for row in board['backlog'] if 'Pregled temperatura' in row['title']]
        self.assertTrue(missed)
        for row in missed:
            self.assertFalse(row['can_confirm'])
            self.assertFalse(row['href'])
        self.assertLessEqual(len(board['backlog_preview']), 3)
        self.assertEqual(board['backlog_more'], max(0, len(board['backlog']) - 3))
        self.assertContains(home, 'Nije dostupno za naknadni unos')
        self.assertNotContains(home, reverse('task_done', args=[missed[0]['id']]))
        if board['backlog_more']:
            self.assertContains(home, 'Još')

    def test_tasks_page_sections_without_listing_each_open_receipt(self):
        with self.at_now():
            r1 = create_goods_receipt(self.org, self.staff, received_on=NOW.date())
            r2 = create_goods_receipt(self.org, self.staff, received_on=NOW.date())
            page = self.client.get(reverse('tasks'))
        self.assertContains(page, 'Aktivni')
        self.assertContains(page, 'Završeni')
        self.assertContains(page, 'Propušteni')
        self.assertContains(page, 'Prijem sirovina', count=1)
        self.assertContains(page, 'Novi prijem')
        self.assertContains(page, '2 nezavršenih')
        self.assertContains(page, 'Istorija prijema')
        self.assertNotContains(page, f'Prijem #{r1.pk}')
        self.assertNotContains(page, f'Prijem #{r2.pk}')
        self.assertNotContains(page, 'Brza akcija · Nije dostupno')

    def test_confirm_task_execution_unchanged(self):
        with self.at_now():
            board = load_task_board(self.org, today=NOW.date())
        confirmable = [row for row in board['for_today'] if row['can_confirm']]
        self.assertTrue(confirmable)
        row = confirmable[0]
        response = self.client.post(reverse('task_done', args=[row['id']]), {'next': 'today'})
        self.assertEqual(response.status_code, 302)
        occurrence = TaskOccurrence.objects.get(pk=row['id'])
        self.assertEqual(occurrence.status, TaskOccurrence.Status.DONE)

    def test_open_receipt_data_unchanged_via_open_list(self):
        with self.at_now():
            receipt = create_goods_receipt(self.org, self.staff, received_on=NOW.date())
        detail = self.client.get(
            f"{reverse('receiving_detail', args=[receipt.pk])}?from=receiving_open"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context['receipt'].pk, receipt.pk)
        self.assertEqual(detail.context['receipt'].status, GoodsReceipt.Status.OPEN)
        self.assertFalse(detail.context['readonly'])
        self.assertContains(detail, 'Dodaj stavku')
        self.assertContains(detail, 'Završi prijem')
