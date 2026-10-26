from datetime import date, datetime
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from ops.models import GoodsReceipt, GoodsReceiptLine, OrganizationTask, TaskOccurrence
from ops.scheduling import BELGRADE, assign_organization_tasks
from organizations.models import Industry, Organization

NOW = datetime(2026, 10, 16, 8, 0, tzinfo=BELGRADE)


class ReceivingUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org = Organization.objects.create(
            name='UI Prijem A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.other = Organization.objects.create(
            name='UI Prijem B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.owner = User.objects.create_user(
            username='ui-prijem-vlasnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.OWNER,
            first_name='Ana',
            last_name='Vlasnik',
        )
        self.staff = User.objects.create_user(
            username='ui-prijem-radnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.STAFF,
            first_name='Mila',
            last_name='Radnik',
        )
        self.other_staff = User.objects.create_user(
            username='ui-prijem-drugi',
            password='test-pass',
            organization=self.other,
            role=User.Role.STAFF,
        )
        self.admin = User.objects.create_user(
            username='ui-prijem-admin',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )
        assign_organization_tasks(self.org, on_date=started)
        assign_organization_tasks(self.other, on_date=started)
        self.client.force_login(self.staff)

    def at_now(self):
        return patch('ops.models.timezone.now', return_value=NOW)

    def line_payload(self, **overrides):
        data = {
            'action': 'add_line',
            'raw_material': 'Brašno T-500',
            'manufacturer': 'Mlin',
            'quantity': '25 kg',
            'visual_check': GoodsReceiptLine.Check.OK,
            'product_safety': GoodsReceiptLine.Check.OK,
            'note': '',
        }
        data.update(overrides)
        return data

    def create_receipt(self):
        with self.at_now():
            return self.client.post(reverse('receiving_create'), {'next': 'today'})

    def test_post_creates_receipt_and_get_does_not(self):
        before = GoodsReceipt.objects.count()
        with self.at_now():
            get_response = self.client.get(reverse('receiving_create'))
            list_get = self.client.get(reverse('receiving_list'))
        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(list_get.status_code, 200)
        self.assertEqual(GoodsReceipt.objects.count(), before)

        response = self.create_receipt()
        self.assertEqual(response.status_code, 302)
        receipt = GoodsReceipt.objects.get(organization=self.org)
        self.assertTrue(
            response.url.startswith(reverse('receiving_detail', args=[receipt.pk]))
        )
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)
        self.assertIsNotNone(receipt.task_occurrence_id)
        self.assertEqual(receipt.task_occurrence.cadence, 'event')
        self.assertEqual(receipt.created_by, self.staff)

    def test_multiple_receipts_same_day_via_ui(self):
        first = self.create_receipt()
        second = self.create_receipt()
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(
            GoodsReceipt.objects.filter(organization=self.org, received_on=NOW.date()).count(),
            2,
        )
        self.assertEqual(
            TaskOccurrence.objects.filter(
                organization=self.org,
                organization_task__definition__record_key='receiving',
                period_start=NOW.date(),
            ).count(),
            2,
        )

    def test_add_update_delete_lines_and_complete(self):
        self.create_receipt()
        receipt = GoodsReceipt.objects.get(organization=self.org)
        detail = reverse('receiving_detail', args=[receipt.pk])

        add = self.client.post(detail, self.line_payload())
        self.assertEqual(add.status_code, 302)
        line = receipt.lines.get()
        self.assertEqual(line.raw_material, 'Brašno T-500')

        prefix = f'l{line.pk}'
        update = self.client.post(detail, {
            'action': 'update_line',
            'line_id': line.pk,
            f'{prefix}-raw_material': 'Brašno T-400',
            f'{prefix}-manufacturer': 'Mlin',
            f'{prefix}-quantity': '50 kg',
            f'{prefix}-visual_check': GoodsReceiptLine.Check.OK,
            f'{prefix}-product_safety': GoodsReceiptLine.Check.OK,
            f'{prefix}-note': 'druga paleta',
        })
        self.assertEqual(update.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.raw_material, 'Brašno T-400')
        self.assertEqual(line.quantity, '50 kg')

        self.client.post(detail, self.line_payload(raw_material='Ulje', quantity='10 l'))
        second = receipt.lines.exclude(pk=line.pk).get()
        delete = self.client.post(detail, {'action': 'delete_line', 'line_id': second.pk})
        self.assertEqual(delete.status_code, 302)
        self.assertEqual(receipt.lines.count(), 1)

        with self.at_now():
            complete = self.client.post(detail, {'action': 'complete'})
        self.assertEqual(complete.status_code, 302)
        receipt.refresh_from_db()
        occurrence = receipt.task_occurrence
        occurrence.refresh_from_db()
        page = self.client.get(detail)
        self.assertEqual(receipt.status, GoodsReceipt.Status.DONE)
        self.assertEqual(occurrence.status, TaskOccurrence.Status.DONE)
        self.assertEqual(occurrence.result, TaskOccurrence.Result.PASSED)
        self.assertContains(page, 'Ispravno')
        self.assertContains(page, 'Mila Radnik')
        self.assertNotContains(page, 'Završi prijem')
        self.assertNotContains(page, 'Dodaj stavku')

    def test_incomplete_complete_keeps_lines(self):
        self.create_receipt()
        receipt = GoodsReceipt.objects.get(organization=self.org)
        detail = reverse('receiving_detail', args=[receipt.pk])
        self.client.post(detail, self.line_payload())
        GoodsReceiptLine.objects.filter(goods_receipt=receipt).update(manufacturer='')
        response = self.client.post(detail, {'action': 'complete'})
        self.assertEqual(response.status_code, 302)
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, GoodsReceipt.Status.OPEN)
        self.assertEqual(receipt.lines.count(), 1)
        page = self.client.get(detail)
        self.assertContains(page, 'Brašno T-500')

    def test_finished_receipt_rejects_line_changes(self):
        self.create_receipt()
        receipt = GoodsReceipt.objects.get(organization=self.org)
        detail = reverse('receiving_detail', args=[receipt.pk])
        self.client.post(detail, self.line_payload())
        with self.at_now():
            self.client.post(detail, {'action': 'complete'})
        line = receipt.lines.get()
        self.client.post(detail, self.line_payload(raw_material='Ulje'))
        prefix = f'l{line.pk}'
        self.client.post(detail, {
            'action': 'update_line',
            'line_id': line.pk,
            f'{prefix}-raw_material': 'Promena',
            f'{prefix}-manufacturer': 'Mlin',
            f'{prefix}-quantity': '1 kg',
            f'{prefix}-visual_check': GoodsReceiptLine.Check.OK,
            f'{prefix}-product_safety': GoodsReceiptLine.Check.OK,
            f'{prefix}-note': '',
        })
        self.client.post(detail, {'action': 'delete_line', 'line_id': line.pk})
        line.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual(line.raw_material, 'Brašno T-500')
        self.assertEqual(receipt.lines.count(), 1)
        self.assertEqual(receipt.status, GoodsReceipt.Status.DONE)

    def test_isolation_and_roles(self):
        self.create_receipt()
        receipt = GoodsReceipt.objects.get(organization=self.org)
        detail = reverse('receiving_detail', args=[receipt.pk])

        self.client.force_login(self.other_staff)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.post(detail, self.line_payload()).status_code, 404)
        self.assertEqual(self.client.post(reverse('receiving_create')).status_code, 302)
        self.assertFalse(GoodsReceipt.objects.filter(organization=self.org, created_by=self.other_staff).exists())
        self.assertTrue(GoodsReceipt.objects.filter(organization=self.other).exists())

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('receiving_list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('receiving_create')).status_code, 403)
        chosen = self.client.get(reverse('receiving_list'), {'objekat': self.org.pk})
        self.assertEqual(chosen.status_code, 200)
        created = self.client.post(reverse('receiving_create'), {'next': 'list'})
        self.assertEqual(created.status_code, 302)
        self.assertTrue(GoodsReceipt.objects.filter(organization=self.org, created_by=self.admin).exists())

        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.post(reverse('receiving_create')).status_code, 302)

    def test_csrf_and_methods(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        bare = csrf_client.post(reverse('receiving_create'), {'next': 'today'})
        self.assertEqual(bare.status_code, 403)
        self.assertEqual(GoodsReceipt.objects.count(), 0)

        page = csrf_client.get(reverse('today'))
        token = str(page.context['csrf_token'])
        with self.at_now():
            ok = csrf_client.post(
                reverse('receiving_create'),
                {'next': 'today', 'csrfmiddlewaretoken': token},
            )
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(csrf_client.get(reverse('receiving_create')).status_code, 405)

    def test_inactive_receiving_blocks_create(self):
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
        response = self.create_receipt()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('today'))
        self.assertEqual(GoodsReceipt.objects.filter(organization=self.org).count(), 0)
        with self.at_now():
            home = self.client.get(reverse('today'))
        self.assertNotContains(home, reverse('receiving_create'))

    def test_list_shows_status_and_result(self):
        self.create_receipt()
        receipt = GoodsReceipt.objects.get(organization=self.org)
        detail = reverse('receiving_detail', args=[receipt.pk])
        self.client.post(detail, self.line_payload(
            visual_check=GoodsReceiptLine.Check.NOT_OK,
            note='oštećeno',
        ))
        with self.at_now():
            self.client.post(detail, {'action': 'complete'})
        listing = self.client.get(reverse('receiving_list'))
        self.assertContains(listing, 'Neispravno')
        self.assertContains(listing, 'Mila Radnik')
        self.assertContains(listing, reverse('receiving_detail', args=[receipt.pk]))
        page = self.client.get(detail)
        self.assertContains(page, 'Neispravno')
        self.assertNotContains(page, 'name="action" value="complete"')
