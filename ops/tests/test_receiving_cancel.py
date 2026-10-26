from datetime import date, datetime
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from ops.models import GoodsReceipt, GoodsReceiptLine, TaskOccurrence
from ops.receiving import (
    add_goods_receipt_line,
    cancel_goods_receipt,
    complete_goods_receipt,
    create_goods_receipt,
    delete_goods_receipt_line,
    update_goods_receipt_line,
    verify_goods_receipt,
)
from ops.scheduling import BELGRADE, assign_organization_tasks
from ops.task_board import load_task_board
from organizations.models import Industry, Organization

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=BELGRADE)
DAY = date(2026, 10, 23)


class ReceivingCancelServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org = Organization.objects.create(
            name='Otkaz Prijem A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.other = Organization.objects.create(
            name='Otkaz Prijem B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.owner = User.objects.create_user(
            username='otkaz-vlasnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.OWNER,
            first_name='Ana',
            last_name='Vlasnik',
        )
        self.staff = User.objects.create_user(
            username='otkaz-radnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.STAFF,
            first_name='Mila',
            last_name='Radnik',
        )
        self.other_staff = User.objects.create_user(
            username='otkaz-drugi',
            password='test-pass',
            organization=self.other,
            role=User.Role.STAFF,
        )
        self.admin = User.objects.create_user(
            username='otkaz-platforma',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )
        assign_organization_tasks(self.org, on_date=started)
        assign_organization_tasks(self.other, on_date=started)

    def line_data(self, **overrides):
        data = {
            'raw_material': 'Brašno',
            'manufacturer': 'Mlin',
            'quantity': '10 kg',
            'visual_check': GoodsReceiptLine.Check.OK,
            'product_safety': GoodsReceiptLine.Check.OK,
        }
        data.update(overrides)
        return data

    def open_receipt(self, user=None, organization=None):
        return create_goods_receipt(
            organization or self.org,
            user or self.staff,
            received_on=DAY,
        )

    def test_cancel_empty_open_receipt(self):
        receipt = self.open_receipt()
        cancelled = cancel_goods_receipt(
            self.org,
            self.staff,
            receipt,
            reason='Greška',
            when=NOW,
        )
        cancelled.refresh_from_db()
        occurrence = cancelled.task_occurrence
        occurrence.refresh_from_db()
        self.assertEqual(cancelled.status, GoodsReceipt.Status.CANCELLED)
        self.assertEqual(cancelled.cancelled_by, self.staff)
        self.assertEqual(cancelled.cancelled_at, NOW)
        self.assertEqual(cancelled.cancellation_reason, 'Greška')
        self.assertIsNone(cancelled.completed_by)
        self.assertIsNone(cancelled.control_result())
        self.assertEqual(occurrence.status, TaskOccurrence.Status.CANCELLED)
        self.assertIsNone(occurrence.done_by)
        self.assertIsNone(occurrence.done_at)
        self.assertIsNone(occurrence.result)

    def test_cancel_open_receipt_with_lines(self):
        receipt = self.open_receipt()
        add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        cancel_goods_receipt(self.org, self.owner, receipt, when=NOW)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.CANCELLED)
        self.assertEqual(receipt.lines.count(), 1)
        self.assertIsNone(receipt.control_result())
        self.assertEqual(receipt.task_occurrence.status, TaskOccurrence.Status.CANCELLED)
        self.assertIsNone(receipt.task_occurrence.result)

    def test_cannot_cancel_completed_receipt(self):
        receipt = self.open_receipt()
        add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        complete_goods_receipt(self.org, self.staff, receipt, when=NOW)
        with self.assertRaises(ValidationError):
            cancel_goods_receipt(self.org, self.owner, receipt, when=NOW)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.DONE)
        self.assertEqual(receipt.task_occurrence.status, TaskOccurrence.Status.DONE)
        self.assertEqual(receipt.task_occurrence.result, TaskOccurrence.Result.PASSED)

    def test_repeat_cancel_is_idempotent(self):
        receipt = self.open_receipt()
        first = cancel_goods_receipt(self.org, self.staff, receipt, reason='prvi', when=NOW)
        later = datetime(2026, 10, 23, 18, 0, tzinfo=BELGRADE)
        again = cancel_goods_receipt(self.org, self.owner, receipt, reason='drugi', when=later)
        again.refresh_from_db()
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(again.cancelled_by, self.staff)
        self.assertEqual(again.cancelled_at, NOW)
        self.assertEqual(again.cancellation_reason, 'prvi')

    def test_cancelled_receipt_cannot_be_edited_or_completed(self):
        receipt = self.open_receipt()
        line = add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        cancel_goods_receipt(self.org, self.staff, receipt, when=NOW)
        with self.assertRaises(ValidationError):
            add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data(raw_material='Ulje'))
        with self.assertRaises(ValidationError):
            update_goods_receipt_line(self.org, self.staff, line, quantity='99 kg')
        with self.assertRaises(ValidationError):
            delete_goods_receipt_line(self.org, self.staff, line)
        with self.assertRaises(ValidationError):
            complete_goods_receipt(self.org, self.staff, receipt, when=NOW)
        with self.assertRaises(ValidationError):
            verify_goods_receipt(
                self.org,
                self.owner,
                receipt,
                verifier_role='Vlasnik',
                when=NOW,
            )
        line.refresh_from_db()
        self.assertEqual(line.quantity, '10 kg')

    def test_permissions_and_org_isolation(self):
        receipt = self.open_receipt()
        with self.assertRaises(PermissionDenied):
            cancel_goods_receipt(self.org, self.other_staff, receipt, when=NOW)
        with self.assertRaises(GoodsReceipt.DoesNotExist):
            cancel_goods_receipt(self.other, self.other_staff, receipt, when=NOW)

        foreign = self.open_receipt(user=self.other_staff, organization=self.other)
        cancel_goods_receipt(self.other, self.admin, foreign, when=NOW)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, GoodsReceipt.Status.CANCELLED)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

    def test_counters_exclude_cancelled(self):
        open_one = self.open_receipt()
        open_two = self.open_receipt()
        cancel_goods_receipt(self.org, self.staff, open_one, when=NOW)
        with patch('ops.task_board.timezone.now', return_value=NOW):
            board = load_task_board(self.org, today=DAY, from_key='today')
        self.assertEqual(board['counts']['open_receipts'], 1)
        self.assertEqual(len(board['open_receipts']), 1)
        self.assertEqual(board['open_receipts'][0]['receipt_pk'], open_two.pk)


class ReceivingCancelUiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org = Organization.objects.create(
            name='Otkaz UI A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.other = Organization.objects.create(
            name='Otkaz UI B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.staff = User.objects.create_user(
            username='otkaz-ui-radnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.STAFF,
            first_name='Mila',
            last_name='Radnik',
        )
        self.other_staff = User.objects.create_user(
            username='otkaz-ui-drugi',
            password='test-pass',
            organization=self.other,
            role=User.Role.STAFF,
        )
        assign_organization_tasks(self.org, on_date=started)
        assign_organization_tasks(self.other, on_date=started)
        self.client.force_login(self.staff)

    def open_receipt(self):
        with patch('ops.task_board.timezone.now', return_value=NOW):
            return create_goods_receipt(self.org, self.staff, received_on=DAY)

    def test_cancel_via_post_with_confirm(self):
        receipt = self.open_receipt()
        detail = reverse('receiving_detail', args=[receipt.pk])
        page = self.client.get(detail)
        self.assertContains(page, 'Otkaži prijem')
        self.assertContains(page, 'name="action" value="cancel"')

        denied = self.client.post(detail, {
            'action': 'cancel',
            'cancellation_reason': 'test',
        })
        self.assertEqual(denied.status_code, 200)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

        response = self.client.post(detail, {
            'action': 'cancel',
            'confirm_cancel': 'on',
            'cancellation_reason': 'Otvoreno greškom',
            'from': 'receiving_open',
        })
        self.assertEqual(response.status_code, 302)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.CANCELLED)
        self.assertEqual(receipt.cancelled_by, self.staff)
        self.assertEqual(receipt.cancellation_reason, 'Otvoreno greškom')

        locked = self.client.get(detail)
        self.assertContains(locked, 'Otkazano')
        self.assertContains(locked, 'Otkazao')
        self.assertNotContains(locked, 'Završi prijem')
        self.assertNotContains(locked, 'Dodaj stavku')
        self.assertContains(locked, 'Istorija')

    def test_history_shows_cancelled_open_list_does_not(self):
        receipt = self.open_receipt()
        cancel_goods_receipt(self.org, self.staff, receipt, reason='ui', when=NOW)
        listing = self.client.get(reverse('receiving_list'))
        self.assertContains(listing, 'Otkazano')
        self.assertContains(listing, reverse('receiving_detail', args=[receipt.pk]))
        open_page = self.client.get(reverse('receiving_open'))
        self.assertNotContains(open_page, f'Prijem #{receipt.pk}')

        with patch('ops.task_board.timezone.now', return_value=NOW):
            home = self.client.get(reverse('today'))
        self.assertNotContains(home, 'Otvoreni prijemi')
        self.assertEqual(home.context['open_receipts_count'], 0)

    def test_csrf_and_get_cannot_cancel(self):
        receipt = self.open_receipt()
        detail = reverse('receiving_detail', args=[receipt.pk])
        bare = Client(enforce_csrf_checks=True)
        bare.force_login(self.staff)
        csrf_denied = bare.post(detail, {
            'action': 'cancel',
            'confirm_cancel': 'on',
        })
        self.assertEqual(csrf_denied.status_code, 403)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

        get_response = self.client.get(detail, {'action': 'cancel'})
        self.assertEqual(get_response.status_code, 200)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

    def test_other_org_cannot_cancel(self):
        receipt = self.open_receipt()
        self.client.force_login(self.other_staff)
        response = self.client.post(
            reverse('receiving_detail', args=[receipt.pk]),
            {'action': 'cancel', 'confirm_cancel': 'on'},
        )
        self.assertEqual(response.status_code, 404)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

    def test_platform_admin_needs_selected_org(self):
        receipt = self.open_receipt()
        admin = User.objects.create_user(
            username='otkaz-ui-admin',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )
        self.client.force_login(admin)
        denied = self.client.post(
            reverse('receiving_detail', args=[receipt.pk]),
            {'action': 'cancel', 'confirm_cancel': 'on'},
        )
        self.assertEqual(denied.status_code, 403)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

        self.client.get(reverse('receiving_list'), {'objekat': self.org.pk})
        ok = self.client.post(
            reverse('receiving_detail', args=[receipt.pk]),
            {'action': 'cancel', 'confirm_cancel': 'on', 'cancellation_reason': 'admin'},
        )
        self.assertEqual(ok.status_code, 302)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.CANCELLED)
        self.assertEqual(receipt.cancelled_by, admin)
