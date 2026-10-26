from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from ops.models import GoodsReceipt, GoodsReceiptLine, TaskDefinition, TaskOccurrence
from ops.scheduling import BELGRADE, assign_organization_tasks
from organizations.models import Industry, Organization


class GoodsReceiptTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org = Organization.objects.create(
            name='Prijem A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.other = Organization.objects.create(
            name='Prijem B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.receiver = User.objects.create_user(
            username='prijem-radnik',
            password='test-pass',
            first_name='Mila',
            last_name='Radnik',
        )
        self.verifier = User.objects.create_user(
            username='prijem-verifikator',
            password='test-pass',
            first_name='Jovan',
            last_name='Tim',
        )
        assign_organization_tasks(self.org, on_date=started)
        assign_organization_tasks(self.other, on_date=started)
        self.when = datetime(2026, 10, 16, 9, 30, tzinfo=BELGRADE)

    def receipt(self, organization=None, day=None):
        return GoodsReceipt.objects.create(
            organization=organization or self.org,
            received_on=day or date(2026, 10, 16),
            created_by=self.receiver,
        )

    def line(self, receipt, **overrides):
        data = {
            'goods_receipt': receipt,
            'sort_order': receipt.lines.count() + 1,
            'raw_material': 'Brašno T-500',
            'manufacturer': 'Mlin',
            'quantity': '25 kg',
            'visual_check': GoodsReceiptLine.Check.OK,
            'product_safety': GoodsReceiptLine.Check.OK,
        }
        data.update(overrides)
        return GoodsReceiptLine.objects.create(**data)

    def occurrence(self, organization, code='t3'):
        task = organization.organization_tasks.get(definition__code=code)
        return TaskOccurrence.objects.create(
            organization=organization,
            organization_task=task,
            cadence=TaskDefinition.Cadence.EVENT,
            period_start=date(2026, 10, 16),
            period_end=date(2026, 10, 16),
        )

    def finish(self, receipt):
        receipt.status = GoodsReceipt.Status.DONE
        receipt.completed_by = self.receiver
        receipt.completed_at = self.when
        receipt.save()

    def test_one_receipt_holds_several_lines(self):
        receipt = self.receipt()
        first = self.line(receipt, raw_material='Brašno T-500', quantity='25 kg')
        second = self.line(receipt, raw_material='Ulje', manufacturer='Uljara', quantity='10 l', sort_order=2)
        self.assertEqual(list(receipt.lines.values_list('raw_material', flat=True)), ['Brašno T-500', 'Ulje'])
        self.assertEqual(first.goods_receipt_id, second.goods_receipt_id)

    def test_same_organization_can_receive_twice_on_one_day(self):
        day = date(2026, 10, 16)
        first = self.receipt(day=day)
        second = self.receipt(day=day)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(
            GoodsReceipt.objects.filter(organization=self.org, received_on=day).count(),
            2,
        )

    def test_passed_result_needs_every_check_ok(self):
        receipt = self.receipt()
        self.line(receipt, raw_material='Brašno')
        self.line(receipt, raw_material='Ulje', quantity='10 l')
        self.assertIsNone(receipt.verified_by_id)
        self.finish(receipt)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.DONE)
        self.assertEqual(receipt.control_result(), TaskOccurrence.Result.PASSED)
        self.assertIsNone(receipt.verified_by_id)
        self.assertEqual(receipt.completed_by, self.receiver)
        self.assertEqual(receipt.completed_at, self.when)

    def test_one_failed_check_fails_the_receipt_and_keeps_it_done(self):
        receipt = self.receipt()
        self.line(receipt, raw_material='Brašno')
        self.line(
            receipt,
            raw_material='Ulje',
            visual_check=GoodsReceiptLine.Check.NOT_OK,
            note='oštećena ambalaža',
        )
        self.finish(receipt)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.DONE)
        self.assertEqual(receipt.control_result(), TaskOccurrence.Result.FAILED)

    def test_incomplete_lines_cannot_be_finished(self):
        receipt = self.receipt()
        self.line(receipt, manufacturer='  ', quantity='')
        receipt.status = GoodsReceipt.Status.DONE
        receipt.completed_by = self.receiver
        receipt.completed_at = self.when
        with self.assertRaises(ValidationError):
            receipt.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)
        self.assertIsNone(receipt.control_result())

        empty = self.receipt()
        empty.status = GoodsReceipt.Status.DONE
        empty.completed_by = self.receiver
        empty.completed_at = self.when
        with self.assertRaises(ValidationError):
            empty.save()
        empty.refresh_from_db()
        self.assertEqual(empty.status, GoodsReceipt.Status.OPEN)

    def test_occurrence_must_belong_to_the_same_organization(self):
        receipt = self.receipt()
        own = self.occurrence(self.org)
        receipt.task_occurrence = own
        receipt.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.task_occurrence, own)

        foreign = self.occurrence(self.other)
        other_receipt = self.receipt()
        other_receipt.task_occurrence = foreign
        with self.assertRaises(ValidationError):
            other_receipt.save()
        other_receipt.refresh_from_db()
        self.assertIsNone(other_receipt.task_occurrence_id)

        duplicate = self.receipt()
        duplicate.task_occurrence = own
        with self.assertRaises(ValidationError):
            duplicate.save()

    def test_finished_receipt_and_its_lines_stay_as_recorded(self):
        receipt = self.receipt()
        item = self.line(receipt, raw_material='Brašno', note='prva isporuka')
        self.finish(receipt)
        original_day = receipt.received_on
        original_note = item.note

        receipt.received_on = date(2026, 10, 17)
        with self.assertRaises(ValidationError):
            receipt.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.received_on, original_day)
        self.assertEqual(receipt.completed_by, self.receiver)
        self.assertEqual(receipt.completed_at, self.when)

        receipt.status = GoodsReceipt.Status.OPEN
        with self.assertRaises(ValidationError):
            receipt.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.DONE)

        item.raw_material = 'Šećer'
        with self.assertRaises(ValidationError):
            item.save()
        item.refresh_from_db()
        self.assertEqual(item.raw_material, 'Brašno')
        self.assertEqual(item.note, original_note)

        with self.assertRaises(ValidationError):
            item.delete()
        with self.assertRaises(ValidationError):
            receipt.delete()
        self.assertTrue(GoodsReceipt.objects.filter(pk=receipt.pk).exists())
        self.assertTrue(GoodsReceiptLine.objects.filter(pk=item.pk).exists())

    def test_verification_is_separate_and_not_granted_to_the_receiver(self):
        receipt = self.receipt()
        self.line(receipt)
        receipt.verified_on = date(2026, 10, 16)
        receipt.verified_by = self.verifier
        receipt.verifier_role = 'Vođa HACCP tima'
        receipt.verified_at = self.when
        with self.assertRaises(ValidationError):
            receipt.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)
        self.assertIsNone(receipt.verified_by_id)

        self.finish(receipt)
        receipt.verified_on = date(2026, 10, 17)
        receipt.verified_by = self.receiver
        receipt.verifier_role = 'Vođa HACCP tima'
        receipt.verified_at = self.when
        with self.assertRaises(ValidationError):
            receipt.save()
        receipt.refresh_from_db()
        self.assertIsNone(receipt.verified_by_id)

        receipt.verified_by = self.verifier
        receipt.verifier_role = ''
        with self.assertRaises(ValidationError):
            receipt.save()

        receipt.verifier_role = 'Vođa HACCP tima'
        receipt.verified_on = date(2026, 10, 17)
        receipt.verified_at = self.when
        receipt.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.verified_by, self.verifier)
        self.assertEqual(receipt.completed_by, self.receiver)
        self.assertNotEqual(receipt.verified_by_id, receipt.completed_by_id)

        receipt.verifier_role = 'Vlasnik'
        with self.assertRaises(ValidationError):
            receipt.save()
        receipt.refresh_from_db()
        self.assertEqual(receipt.verifier_role, 'Vođa HACCP tima')
