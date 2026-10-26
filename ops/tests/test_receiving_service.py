from datetime import date, datetime
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from accounts.models import User
from ops.models import GoodsReceipt, GoodsReceiptLine, OrganizationTask, TaskOccurrence
from ops.receiving import (
    add_goods_receipt_line,
    complete_goods_receipt,
    create_goods_receipt,
    delete_goods_receipt_line,
    update_goods_receipt_line,
    verify_goods_receipt,
)
from ops.scheduling import BELGRADE, assign_organization_tasks
from organizations.models import Industry, Organization


class ReceivingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org = Organization.objects.create(
            name='Servis Prijem A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.other = Organization.objects.create(
            name='Servis Prijem B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.owner = User.objects.create_user(
            username='prijem-vlasnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.OWNER,
            first_name='Ana',
            last_name='Vlasnik',
        )
        self.staff = User.objects.create_user(
            username='prijem-zaposleni',
            password='test-pass',
            organization=self.org,
            role=User.Role.STAFF,
            first_name='Mila',
            last_name='Radnik',
        )
        self.other_owner = User.objects.create_user(
            username='prijem-vlasnik-b',
            password='test-pass',
            organization=self.other,
            role=User.Role.OWNER,
        )
        self.admin = User.objects.create_user(
            username='prijem-platforma',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )
        assign_organization_tasks(self.org, on_date=started)
        assign_organization_tasks(self.other, on_date=started)
        self.day = date(2026, 10, 16)
        self.when = datetime(2026, 10, 16, 11, 15, tzinfo=BELGRADE)

    def line_data(self, **overrides):
        data = {
            'raw_material': 'Brašno T-500',
            'manufacturer': 'Mlin',
            'quantity': '25 kg',
            'visual_check': GoodsReceiptLine.Check.OK,
            'product_safety': GoodsReceiptLine.Check.OK,
        }
        data.update(overrides)
        return data

    def open_receipt(self, user=None, organization=None, day=None):
        return create_goods_receipt(
            organization or self.org,
            user or self.staff,
            received_on=day or self.day,
        )

    def test_create_receipt_with_event_occurrence(self):
        receipt = self.open_receipt()
        receipt.refresh_from_db()
        occurrence = receipt.task_occurrence
        self.assertIsNotNone(occurrence)
        self.assertEqual(occurrence.organization_id, self.org.pk)
        self.assertEqual(occurrence.cadence, 'event')
        self.assertEqual(occurrence.period_start, self.day)
        self.assertEqual(occurrence.period_end, self.day)
        self.assertEqual(occurrence.status, TaskOccurrence.Status.OPEN)
        self.assertEqual(
            occurrence.organization_task.definition.record_key,
            'receiving',
        )
        self.assertEqual(receipt.created_by, self.staff)
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

    def test_multiple_receipts_on_the_same_day(self):
        first = self.open_receipt()
        second = self.open_receipt()
        self.assertNotEqual(first.pk, second.pk)
        self.assertNotEqual(first.task_occurrence_id, second.task_occurrence_id)
        self.assertEqual(
            GoodsReceipt.objects.filter(organization=self.org, received_on=self.day).count(),
            2,
        )
        self.assertEqual(
            TaskOccurrence.objects.filter(
                organization=self.org,
                organization_task__definition__record_key='receiving',
                period_start=self.day,
            ).count(),
            2,
        )

    def test_add_and_update_lines_while_open(self):
        receipt = self.open_receipt()
        first = add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        second = add_goods_receipt_line(
            self.org,
            self.staff,
            receipt,
            **self.line_data(raw_material='Ulje', quantity='10 l'),
        )
        self.assertEqual(receipt.lines.count(), 2)
        self.assertEqual(first.sort_order, 0)
        self.assertEqual(second.sort_order, 1)

        update_goods_receipt_line(
            self.org,
            self.staff,
            first,
            quantity='50 kg',
            note='druga paleta',
        )
        first.refresh_from_db()
        self.assertEqual(first.quantity, '50 kg')
        self.assertEqual(first.note, 'druga paleta')
        self.assertEqual(first.raw_material, 'Brašno T-500')

        delete_goods_receipt_line(self.org, self.staff, second)
        self.assertEqual(receipt.lines.count(), 1)

    def test_finished_records_cannot_be_changed(self):
        receipt = self.open_receipt()
        line = add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        complete_goods_receipt(self.org, self.staff, receipt, when=self.when)

        with self.assertRaises(ValidationError):
            add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data(raw_material='Ulje'))
        with self.assertRaises(ValidationError):
            update_goods_receipt_line(self.org, self.staff, line, quantity='99 kg')
        with self.assertRaises(ValidationError):
            delete_goods_receipt_line(self.org, self.staff, line)
        line.refresh_from_db()
        self.assertEqual(line.quantity, '25 kg')

    def test_passed_and_failed_results_sync_to_occurrence(self):
        passed = self.open_receipt()
        add_goods_receipt_line(self.org, self.staff, passed, **self.line_data())
        add_goods_receipt_line(
            self.org,
            self.staff,
            passed,
            **self.line_data(raw_material='Ulje', quantity='5 l'),
        )
        complete_goods_receipt(self.org, self.staff, passed, when=self.when)
        passed.refresh_from_db()
        occurrence = passed.task_occurrence
        occurrence.refresh_from_db()
        self.assertEqual(passed.status, GoodsReceipt.Status.DONE)
        self.assertEqual(passed.control_result(), TaskOccurrence.Result.PASSED)
        self.assertEqual(occurrence.status, TaskOccurrence.Status.DONE)
        self.assertEqual(occurrence.result, TaskOccurrence.Result.PASSED)
        self.assertEqual(occurrence.done_by, self.staff)
        self.assertEqual(occurrence.done_at, self.when)
        self.assertEqual(passed.completed_by, self.staff)
        self.assertEqual(passed.completed_at, self.when)

        failed = self.open_receipt()
        add_goods_receipt_line(self.org, self.staff, failed, **self.line_data())
        add_goods_receipt_line(
            self.org,
            self.staff,
            failed,
            **self.line_data(
                raw_material='Jaja',
                visual_check=GoodsReceiptLine.Check.NOT_OK,
                note='oštećeno',
            ),
        )
        complete_goods_receipt(self.org, self.owner, failed, when=self.when)
        failed.refresh_from_db()
        failed_occ = failed.task_occurrence
        failed_occ.refresh_from_db()
        self.assertEqual(failed.status, GoodsReceipt.Status.DONE)
        self.assertEqual(failed.control_result(), TaskOccurrence.Result.FAILED)
        self.assertEqual(failed_occ.result, TaskOccurrence.Result.FAILED)
        self.assertEqual(failed_occ.done_by, self.owner)

    def test_incomplete_data_cannot_complete(self):
        receipt = self.open_receipt()
        with self.assertRaises(ValidationError):
            add_goods_receipt_line(
                self.org,
                self.staff,
                receipt,
                raw_material='Brašno',
                manufacturer='',
                quantity='25 kg',
                visual_check=GoodsReceiptLine.Check.OK,
                product_safety=GoodsReceiptLine.Check.OK,
            )
        with self.assertRaises(ValidationError):
            complete_goods_receipt(self.org, self.staff, receipt, when=self.when)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)
        self.assertEqual(receipt.task_occurrence.status, TaskOccurrence.Status.OPEN)

        orphan = GoodsReceipt.objects.create(
            organization=self.org,
            received_on=self.day,
            created_by=self.staff,
        )
        GoodsReceiptLine.objects.create(
            goods_receipt=orphan,
            **self.line_data(),
        )
        with self.assertRaises(ValidationError):
            complete_goods_receipt(self.org, self.staff, orphan, when=self.when)
        orphan.refresh_from_db()
        self.assertEqual(orphan.status, GoodsReceipt.Status.OPEN)

    def test_repeat_complete_keeps_original_actor_and_time(self):
        receipt = self.open_receipt()
        add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        complete_goods_receipt(self.org, self.staff, receipt, when=self.when)
        later = datetime(2026, 10, 16, 18, 0, tzinfo=BELGRADE)
        again = complete_goods_receipt(self.org, self.owner, receipt, when=later)
        again.refresh_from_db()
        occurrence = again.task_occurrence
        occurrence.refresh_from_db()
        self.assertEqual(again.completed_by, self.staff)
        self.assertEqual(again.completed_at, self.when)
        self.assertEqual(occurrence.done_by, self.staff)
        self.assertEqual(occurrence.done_at, self.when)
        self.assertEqual(occurrence.result, TaskOccurrence.Result.PASSED)

    def test_inactive_receiving_task_blocks_creation(self):
        task = OrganizationTask.objects.get(
            organization=self.org,
            definition__record_key='receiving',
        )
        task.enabled = False
        with patch(
            'ops.models.timezone.now',
            return_value=datetime(2026, 10, 10, 12, 0, tzinfo=BELGRADE),
        ):
            task.save()
        with self.assertRaises(ValidationError):
            create_goods_receipt(self.org, self.staff, received_on=self.day)

        task.enabled = True
        with patch(
            'ops.models.timezone.now',
            return_value=datetime(2026, 10, 20, 12, 0, tzinfo=BELGRADE),
        ):
            task.save()
        receipt = create_goods_receipt(self.org, self.staff, received_on=date(2026, 10, 20))
        self.assertEqual(receipt.received_on, date(2026, 10, 20))
        with self.assertRaises(ValidationError):
            create_goods_receipt(self.org, self.staff, received_on=date(2026, 10, 15))

    def test_other_organization_is_isolated(self):
        receipt = self.open_receipt()
        line = add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        with self.assertRaises(PermissionDenied):
            create_goods_receipt(self.org, self.other_owner, received_on=self.day)
        with self.assertRaises(GoodsReceipt.DoesNotExist):
            add_goods_receipt_line(self.other, self.other_owner, receipt, **self.line_data())
        with self.assertRaises(GoodsReceiptLine.DoesNotExist):
            update_goods_receipt_line(self.other, self.other_owner, line, quantity='1 kg')
        with self.assertRaises(GoodsReceipt.DoesNotExist):
            complete_goods_receipt(self.other, self.other_owner, receipt, when=self.when)
        with self.assertRaises(GoodsReceipt.DoesNotExist):
            verify_goods_receipt(
                self.other,
                self.other_owner,
                receipt,
                verifier_role='Vlasnik',
                when=self.when,
            )
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)

    def test_role_permissions_for_work_and_verification(self):
        orphan = User.objects.create_user(
            username='prijem-bez-objekta',
            password='test-pass',
            role=User.Role.STAFF,
        )
        with self.assertRaises(PermissionDenied):
            create_goods_receipt(self.org, orphan, received_on=self.day)

        receipt = self.open_receipt(user=self.staff)
        add_goods_receipt_line(self.org, self.staff, receipt, **self.line_data())
        complete_goods_receipt(self.org, self.staff, receipt, when=self.when)

        with self.assertRaises(PermissionDenied):
            verify_goods_receipt(
                self.org,
                self.staff,
                receipt,
                verifier_role='Zaposleni',
                when=self.when,
            )

        verified = verify_goods_receipt(
            self.org,
            self.owner,
            receipt,
            verifier_role='Vođa HACCP tima',
            when=self.when,
        )
        verified.refresh_from_db()
        self.assertEqual(verified.verified_by, self.owner)
        self.assertEqual(verified.verifier_role, 'Vođa HACCP tima')
        self.assertEqual(verified.verified_on, self.day)
        self.assertEqual(verified.verified_at, self.when)
        self.assertEqual(verified.control_result(), TaskOccurrence.Result.PASSED)

        admin_receipt = create_goods_receipt(self.org, self.admin, received_on=self.day)
        add_goods_receipt_line(self.org, self.admin, admin_receipt, **self.line_data())
        complete_goods_receipt(self.org, self.admin, admin_receipt, when=self.when)
        with self.assertRaises(ValidationError):
            verify_goods_receipt(
                self.org,
                self.admin,
                admin_receipt,
                verifier_role='Administrator platforme',
                when=self.when,
            )
        admin_verified = verify_goods_receipt(
            self.org,
            self.owner,
            admin_receipt,
            verifier_role='Vlasnik',
            when=self.when,
        )
        self.assertEqual(admin_verified.verified_by, self.owner)

    def test_self_verification_is_forbidden_and_verification_is_once(self):
        receipt = self.open_receipt(user=self.owner)
        add_goods_receipt_line(self.org, self.owner, receipt, **self.line_data())
        complete_goods_receipt(self.org, self.owner, receipt, when=self.when)
        with self.assertRaises(ValidationError):
            verify_goods_receipt(
                self.org,
                self.owner,
                receipt,
                verifier_role='Vlasnik',
                when=self.when,
            )
        receipt.refresh_from_db()
        self.assertIsNone(receipt.verified_by_id)

        first = verify_goods_receipt(
            self.org,
            self.admin,
            receipt,
            verifier_role='Administrator platforme',
            when=self.when,
        )
        later = datetime(2026, 10, 17, 9, 0, tzinfo=BELGRADE)
        again = verify_goods_receipt(
            self.org,
            self.admin,
            receipt,
            verifier_role='Druga funkcija',
            when=later,
        )
        again.refresh_from_db()
        self.assertEqual(again.verified_by, first.verified_by)
        self.assertEqual(again.verifier_role, 'Administrator platforme')
        self.assertEqual(again.verified_at, self.when)
        self.assertEqual(again.control_result(), TaskOccurrence.Result.PASSED)
        self.assertEqual(again.task_occurrence.result, TaskOccurrence.Result.PASSED)
