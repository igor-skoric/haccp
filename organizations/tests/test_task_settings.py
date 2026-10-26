from datetime import date, datetime, time
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from ops.models import OrganizationTask, TaskDefinition, TaskOccurrence
from ops.scheduling import BELGRADE, assign_organization_tasks, ensure_occurrences
from organizations.models import Industry, Organization


class TaskSettingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        started = date(2026, 10, 1)
        self.org_a = Organization.objects.create(
            name='Podešavanje A',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.org_b = Organization.objects.create(
            name='Podešavanje B',
            industry=self.industry,
            tasks_started_on=started,
        )
        self.owner = User.objects.create_user(
            username='vlasnik-zadataka',
            password='test-pass',
            organization=self.org_a,
            role=User.Role.OWNER,
        )
        self.staff = User.objects.create_user(
            username='zaposleni-zadataka',
            password='test-pass',
            organization=self.org_a,
            role=User.Role.STAFF,
        )
        self.admin = User.objects.create_user(
            username='platforma-zadataka',
            password='test-pass',
            role=User.Role.PLATFORM_ADMIN,
        )
        assign_organization_tasks(self.org_a, on_date=started)
        assign_organization_tasks(self.org_b, on_date=started)
        self.only_a = TaskDefinition.objects.create(
            code='samo-podesavanje-a',
            title='Samo objekat A',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.DAILY,
        )
        OrganizationTask.objects.create(
            organization=self.org_a,
            definition=self.only_a,
            active_from=started,
        )
        self.client.force_login(self.owner)

    def task(self, code, organization=None):
        return OrganizationTask.objects.get(
            organization=organization or self.org_a,
            definition__code=code,
        )

    def post_task(self, org_task, **fields):
        payload = {'task': org_task.pk}
        prefix = f't{org_task.pk}-'
        payload.update({f'{prefix}{name}': value for name, value in fields.items()})
        return self.client.post(reverse('task_settings'), payload)

    def at(self, day):
        return patch(
            'ops.models.timezone.now',
            return_value=datetime(2026, 10, day, 12, 0, tzinfo=BELGRADE),
        )

    def test_staff_cannot_open_or_change_tasks(self):
        self.client.force_login(self.staff)
        org_task = self.task('t1')
        self.assertEqual(self.client.get(reverse('task_settings')).status_code, 403)
        self.assertEqual(self.client.get(reverse('settings_config')).status_code, 403)
        response = self.post_task(org_task, due_time='18:30')
        self.assertEqual(response.status_code, 403)
        org_task.refresh_from_db()
        self.assertIsNone(org_task.due_time)
        self.assertTrue(org_task.enabled)

    def test_owner_sees_only_their_tasks(self):
        response = self.client.get(reverse('task_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'Samo objekat A')
        self.assertContains(response, 'Važi od 01.10.2026.')
        self.assertContains(response, 'Nedeljno čišćenje vitrina')
        config = self.client.get(reverse('settings_config'))
        self.assertContains(config, 'Zadaci')
        self.client.force_login(User.objects.create_user(
            username='vlasnik-b-zadaci',
            password='test-pass',
            organization=self.org_b,
            role=User.Role.OWNER,
        ))
        other = self.client.get(reverse('task_settings'))
        self.assertNotContains(other, 'Samo objekat A')

    def test_other_organization_task_is_not_changed(self):
        foreign = self.task('t1', self.org_b)
        response = self.post_task(foreign, due_time='19:00')
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertTrue(foreign.enabled)
        self.assertIsNone(foreign.due_time)

    def test_platform_admin_is_limited_to_the_selected_organization(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('task_settings')).status_code, 403)
        self.assertEqual(self.post_task(self.task('t1'), due_time='19:00').status_code, 403)
        opened = self.client.get(reverse('task_settings'), {'objekat': self.org_b.pk})
        self.assertEqual(opened.status_code, 200)
        self.assertNotContains(opened, 'Samo objekat A')
        self.assertContains(opened, 'Pregled temperatura vitrina')
        foreign = self.task('samo-podesavanje-a')
        denied = self.post_task(foreign, due_time='19:00')
        self.assertEqual(denied.status_code, 404)
        foreign.refresh_from_db()
        self.assertIsNone(foreign.due_time)

    def test_schedule_change_keeps_existing_due_at(self):
        ensure_occurrences(self.org_a, today=date(2026, 10, 16), lookback_days=0)
        daily = self.task('t1')
        current = TaskOccurrence.objects.get(organization_task=daily, period_start=date(2026, 10, 16))
        original = current.due_at
        weekly = self.task('t2w')
        week = TaskOccurrence.objects.get(organization_task=weekly, period_start=date(2026, 10, 12))
        original_week = week.due_at

        response = self.post_task(daily, enabled='on', due_time='18:30')
        self.assertEqual(response.status_code, 302)
        daily.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(daily.due_time, time(18, 30))
        self.assertEqual(current.due_at, original)
        self.assertEqual(daily.active_from, date(2026, 10, 1))

        response = self.post_task(weekly, enabled='on', weekday='0')
        self.assertEqual(response.status_code, 302)
        weekly.refresh_from_db()
        week.refresh_from_db()
        self.assertEqual(weekly.weekday, 0)
        self.assertEqual(week.due_at, original_week)

        ensure_occurrences(self.org_a, today=date(2026, 10, 17), lookback_days=1)
        current.refresh_from_db()
        week.refresh_from_db()
        nxt = TaskOccurrence.objects.get(organization_task=daily, period_start=date(2026, 10, 17))
        self.assertEqual(current.due_at, original)
        self.assertEqual(timezone.localtime(nxt.due_at, BELGRADE).time().replace(microsecond=0), time(18, 30))
        ensure_occurrences(self.org_a, today=date(2026, 10, 21), lookback_days=0)
        week.refresh_from_db()
        following = TaskOccurrence.objects.get(organization_task=weekly, period_start=date(2026, 10, 19))
        self.assertEqual(week.due_at, original_week)
        self.assertEqual(timezone.localtime(following.due_at, BELGRADE).date(), date(2026, 10, 19))

    def test_disable_and_reenable_records_the_gap(self):
        daily = self.task('t1')
        done_at = datetime(2026, 10, 2, 9, 0, tzinfo=BELGRADE)
        done = TaskOccurrence.objects.create(
            organization=self.org_a,
            organization_task=daily,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=date(2026, 10, 2),
            period_end=date(2026, 10, 2),
            due_at=datetime(2026, 10, 2, 10, 0, tzinfo=BELGRADE),
            status=TaskOccurrence.Status.DONE,
            done_by=self.owner,
            done_at=done_at,
        )
        with self.at(10):
            response = self.post_task(daily, due_time='10:00')
        self.assertEqual(response.status_code, 302)
        daily.refresh_from_db()
        self.assertFalse(daily.enabled)
        closed = daily.activations.get(ended_on=date(2026, 10, 10))
        self.assertEqual(closed.started_on, date(2026, 10, 1))

        with self.at(20):
            response = self.post_task(daily, enabled='on', due_time='10:00')
        self.assertEqual(response.status_code, 302)
        daily.refresh_from_db()
        self.assertTrue(daily.enabled)
        opened = daily.activations.get(ended_on__isnull=True)
        self.assertEqual(opened.started_on, date(2026, 10, 20))
        ensure_occurrences(self.org_a, today=date(2026, 10, 20), lookback_days=35)
        for day in (date(2026, 10, 11), date(2026, 10, 15), date(2026, 10, 19)):
            self.assertFalse(
                TaskOccurrence.objects.filter(organization_task=daily, period_start=day).exists(),
                day,
            )
        done.refresh_from_db()
        self.assertEqual(done.status, TaskOccurrence.Status.DONE)
        self.assertEqual(done.done_by, self.owner)
        self.assertEqual(done.done_at, done_at)
        self.assertEqual(done.due_at, datetime(2026, 10, 2, 10, 0, tzinfo=BELGRADE))

    def test_invalid_schedule_is_rejected(self):
        monthly = TaskDefinition.objects.create(
            code='mesecni-podesavanje',
            title='Mesečno podešavanje',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.MONTHLY,
            monthday=10,
        )
        org_task = OrganizationTask.objects.create(
            organization=self.org_a,
            definition=monthly,
            active_from=date(2026, 10, 1),
        )
        response = self.post_task(org_task, enabled='on', monthday='31', active_from='2020-01-01')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dan u mesecu mora biti od 1 do 28.')
        org_task.refresh_from_db()
        self.assertIsNone(org_task.monthday)
        self.assertEqual(org_task.active_from, date(2026, 10, 1))
        self.assertTrue(org_task.activations.filter(ended_on__isnull=True, started_on=date(2026, 10, 1)).exists())

        daily = self.task('t1')
        self.post_task(daily, enabled='on', due_time='10:00', weekday='3')
        daily.refresh_from_db()
        self.assertIsNone(daily.weekday)
