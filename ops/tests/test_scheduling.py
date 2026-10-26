from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.forms import RegistrationForm
from accounts.models import User
from ops.models import DayTaskDone, HygieneCheck, OrganizationTask, TaskDefinition, TaskOccurrence
from ops.scheduling import (
    BELGRADE,
    _save_new_occurrence,
    assign_organization_tasks,
    ensure_occurrences,
    is_late,
)
from organizations.models import Industry, Organization


class SchedulingTests(TestCase):
    ANCHOR = date(2020, 1, 1)

    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')
        cls.user = User.objects.create_user(
            username='raspored-radnik',
            password='test-pass',
            first_name='Mila',
            last_name='Radnik',
            role=User.Role.STAFF,
        )

    def setUp(self):
        self.org = Organization.objects.create(
            name='Raspored',
            industry=self.industry,
            tasks_started_on=self.ANCHOR,
        )
        self.user.organization = self.org
        self.user.save(update_fields=['organization'])
        assign_organization_tasks(self.org, on_date=self.ANCHOR)

    def only(self, *codes):
        from ops.models import OrganizationTaskActivation

        wanted = set(codes)
        for org_task in OrganizationTask.objects.filter(organization=self.org).select_related('definition'):
            should = org_task.definition.code in wanted
            if org_task.enabled != should:
                org_task.enabled = should
                org_task.save()
            if not should:
                continue
            # Schedule tests expect coverage from active_from, not "today" after re-enable.
            window = org_task.activations.filter(ended_on__isnull=True).order_by('started_on').first()
            if window is None:
                OrganizationTaskActivation.objects.create(
                    organization_task=org_task,
                    started_on=org_task.active_from,
                )
            elif window.started_on > org_task.active_from:
                window.started_on = org_task.active_from
                window.save(update_fields=['started_on'])

    def task(self, code):
        return OrganizationTask.objects.get(organization=self.org, definition__code=code)

    def test_daily_week_and_month_periods(self):
        self.only('t1', 't2w')
        monthly = TaskDefinition.objects.create(
            code='mesecni-pregled',
            title='Mesečni pregled',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.MONTHLY,
            monthday=15,
        )
        OrganizationTask.objects.create(
            organization=self.org,
            definition=monthly,
            active_from=self.ANCHOR,
        )

        ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=0)

        daily = TaskOccurrence.objects.get(organization_task=self.task('t1'))
        self.assertEqual(daily.period_start, date(2026, 10, 16))
        self.assertEqual(daily.period_end, date(2026, 10, 16))
        self.assertEqual(daily.status, TaskOccurrence.Status.OPEN)
        self.assertEqual(timezone.localtime(daily.due_at, BELGRADE).hour, 10)

        weekly = TaskOccurrence.objects.get(organization_task=self.task('t2w'))
        self.assertEqual(weekly.period_start, date(2026, 10, 12))
        self.assertEqual(weekly.period_end, date(2026, 10, 18))
        self.assertEqual(timezone.localtime(weekly.due_at, BELGRADE).date(), date(2026, 10, 16))

        month = TaskOccurrence.objects.get(organization_task__definition=monthly)
        self.assertEqual(month.period_start, date(2026, 10, 1))
        self.assertEqual(month.period_end, date(2026, 10, 31))
        self.assertEqual(timezone.localtime(month.due_at, BELGRADE).date(), date(2026, 10, 15))

        self.assertEqual(ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=0), 0)
        self.assertEqual(TaskOccurrence.objects.filter(organization=self.org).count(), 3)

    def test_year_boundary_and_february(self):
        self.only('t2w')
        monthly = TaskDefinition.objects.create(
            code='mesecni-februar',
            title='Februar',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.MONTHLY,
            monthday=28,
        )
        OrganizationTask.objects.create(
            organization=self.org,
            definition=monthly,
            active_from=self.ANCHOR,
        )

        ensure_occurrences(self.org, today=date(2026, 1, 2), lookback_days=0)
        week = TaskOccurrence.objects.get(organization_task=self.task('t2w'))
        self.assertEqual(week.period_start, date(2025, 12, 29))
        self.assertEqual(week.period_end, date(2026, 1, 4))
        self.assertEqual(timezone.localtime(week.due_at, BELGRADE).date(), date(2026, 1, 2))

        ensure_occurrences(self.org, today=date(2026, 1, 20), lookback_days=40)
        december = TaskOccurrence.objects.get(
            organization_task__definition=monthly,
            period_start=date(2025, 12, 1),
        )
        january = TaskOccurrence.objects.get(
            organization_task__definition=monthly,
            period_start=date(2026, 1, 1),
        )
        self.assertEqual(december.period_end, date(2025, 12, 31))
        self.assertEqual(december.status, TaskOccurrence.Status.MISSED)
        self.assertEqual(timezone.localtime(december.due_at, BELGRADE).date(), date(2025, 12, 28))
        self.assertEqual(january.status, TaskOccurrence.Status.OPEN)
        self.assertEqual(january.period_end, date(2026, 1, 31))

        ensure_occurrences(self.org, today=date(2026, 3, 1), lookback_days=40)
        february = TaskOccurrence.objects.get(
            organization_task__definition=monthly,
            period_start=date(2026, 2, 1),
        )
        self.assertEqual(february.period_end, date(2026, 2, 28))
        self.assertEqual(timezone.localtime(february.due_at, BELGRADE).date(), date(2026, 2, 28))
        self.assertEqual(february.status, TaskOccurrence.Status.MISSED)

        ensure_occurrences(self.org, today=date(2024, 2, 29), lookback_days=0)
        leap = TaskOccurrence.objects.get(
            organization_task__definition=monthly,
            period_start=date(2024, 2, 1),
        )
        self.assertEqual(leap.period_end, date(2024, 2, 29))
        self.assertEqual(timezone.localtime(leap.due_at, BELGRADE).date(), date(2024, 2, 28))
        self.assertEqual(leap.status, TaskOccurrence.Status.OPEN)

    def test_belgrade_day_and_due_offset(self):
        self.only('t1')
        moment = datetime(2026, 7, 15, 22, 30, tzinfo=datetime_timezone.utc)
        with patch('ops.scheduling.timezone.now', return_value=moment):
            ensure_occurrences(self.org, lookback_days=0)
        summer = TaskOccurrence.objects.get(organization_task=self.task('t1'))
        summer_local = timezone.localtime(summer.due_at, BELGRADE)
        self.assertEqual(summer.period_start, date(2026, 7, 16))
        self.assertEqual(summer_local.hour, 10)
        self.assertEqual(summer_local.utcoffset(), timedelta(hours=2))
        self.assertEqual(summer.due_at.astimezone(datetime_timezone.utc).hour, 8)

        ensure_occurrences(self.org, today=date(2026, 1, 15), lookback_days=0)
        winter = TaskOccurrence.objects.get(
            organization_task=self.task('t1'),
            period_start=date(2026, 1, 15),
        )
        winter_local = timezone.localtime(winter.due_at, BELGRADE)
        self.assertEqual(winter_local.hour, 10)
        self.assertEqual(winter_local.utcoffset(), timedelta(hours=1))
        self.assertEqual(winter.due_at.astimezone(datetime_timezone.utc).hour, 9)

    def test_repeat_call_keeps_the_copied_due_at(self):
        self.only('t1')
        ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=0)
        row = TaskOccurrence.objects.get(organization_task=self.task('t1'))
        copied = row.due_at
        definition = row.organization_task.definition
        definition.due_time = time(11, 0)
        definition.save()
        self.assertEqual(ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=0), 0)
        row.refresh_from_db()
        self.assertEqual(row.due_at, copied)
        self.assertEqual(
            TaskOccurrence.objects.filter(organization_task=self.task('t1'), period_start=date(2026, 10, 16)).count(),
            1,
        )

    def test_losing_insert_reuses_the_existing_row(self):
        self.only('t1')
        org_task = self.task('t1')
        existing = TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=date(2026, 10, 16),
            period_end=date(2026, 10, 16),
            due_at=datetime(2026, 10, 16, 10, 0, tzinfo=BELGRADE),
            status=TaskOccurrence.Status.OPEN,
        )
        found, was_created = _save_new_occurrence(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=date(2026, 10, 16),
            period_end=date(2026, 10, 16),
            due_at=datetime(2026, 10, 16, 18, 0, tzinfo=BELGRADE),
            status=TaskOccurrence.Status.OPEN,
        )
        self.assertFalse(was_created)
        self.assertEqual(found.pk, existing.pk)
        found.refresh_from_db()
        self.assertEqual(found.due_at, existing.due_at)
        self.assertEqual(
            TaskOccurrence.objects.filter(organization_task=org_task, period_start=date(2026, 10, 16)).count(),
            1,
        )

    def test_expired_period_becomes_missed_and_the_next_one_opens(self):
        self.only('t1')
        org_task = self.task('t1')
        yesterday = TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=date(2026, 10, 15),
            period_end=date(2026, 10, 15),
            due_at=datetime(2026, 10, 15, 10, 0, tzinfo=BELGRADE),
            status=TaskOccurrence.Status.OPEN,
        )
        ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=1)
        yesterday.refresh_from_db()
        self.assertEqual(yesterday.status, TaskOccurrence.Status.MISSED)
        self.assertEqual(yesterday.due_at, datetime(2026, 10, 15, 10, 0, tzinfo=BELGRADE))
        current = TaskOccurrence.objects.get(organization_task=org_task, period_start=date(2026, 10, 16))
        self.assertEqual(current.status, TaskOccurrence.Status.OPEN)
        self.assertIsNone(current.done_at)

        done_at = datetime(2026, 10, 16, 11, 30, tzinfo=BELGRADE)
        current.status = TaskOccurrence.Status.DONE
        current.done_at = done_at
        current.done_by = self.user
        current.save()
        self.assertTrue(is_late(current))
        ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=1)
        current.refresh_from_db()
        self.assertEqual(current.status, TaskOccurrence.Status.DONE)
        self.assertEqual(current.done_at, done_at)
        self.assertEqual(current.done_by, self.user)

    def test_legacy_weekly_completion_does_not_block_the_next_week(self):
        self.only('t4')
        org_task = self.task('t4')
        self.assertTrue(org_task.enabled)
        self.assertTrue(org_task.activations.filter(ended_on__isnull=True).exists())
        done_at = datetime(2026, 10, 14, 9, 15, tzinfo=BELGRADE)
        legacy = DayTaskDone.objects.create(
            organization=self.org,
            work_date=date(2026, 10, 14),
            code='t4',
            done_by=self.user,
        )
        DayTaskDone.objects.filter(pk=legacy.pk).update(done_at=done_at)
        legacy.refresh_from_db()
        historical = TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.WEEKLY,
            period_start=date(2026, 10, 14),
            period_end=date(2026, 10, 14),
            status=TaskOccurrence.Status.DONE,
            done_by=self.user,
            done_at=done_at,
            legacy_day_task_id=legacy.pk,
        )
        check = HygieneCheck.objects.create(
            organization=self.org,
            work_date=date(2026, 10, 14),
            created_by=self.user,
            note='netaknuto',
        )

        ensure_occurrences(self.org, today=date(2026, 10, 21), lookback_days=7)

        historical.refresh_from_db()
        legacy.refresh_from_db()
        check.refresh_from_db()
        self.assertEqual(historical.period_start, date(2026, 10, 12))
        self.assertEqual(historical.period_end, date(2026, 10, 18))
        self.assertEqual(historical.status, TaskOccurrence.Status.DONE)
        self.assertEqual(historical.done_at, done_at)
        self.assertEqual(historical.done_by, self.user)
        self.assertEqual(legacy.work_date, date(2026, 10, 14))
        self.assertEqual(legacy.done_at, done_at)
        self.assertEqual(legacy.done_by, self.user)
        self.assertEqual(check.note, 'netaknuto')
        self.assertEqual(check.work_date, date(2026, 10, 14))
        current = TaskOccurrence.objects.get(organization_task=org_task, period_start=date(2026, 10, 19))
        self.assertEqual(current.status, TaskOccurrence.Status.OPEN)
        self.assertEqual(
            TaskOccurrence.objects.filter(organization_task=org_task, period_start=date(2026, 10, 12)).count(),
            1,
        )

    def test_second_legacy_completion_in_the_same_week_keeps_its_day(self):
        self.only('t4')
        org_task = self.task('t4')
        first_done = datetime(2026, 10, 12, 8, 0, tzinfo=BELGRADE)
        second_done = datetime(2026, 10, 14, 8, 0, tzinfo=BELGRADE)
        first_legacy = DayTaskDone.objects.create(
            organization=self.org,
            work_date=date(2026, 10, 12),
            code='t4',
            done_by=self.user,
        )
        second_legacy = DayTaskDone.objects.create(
            organization=self.org,
            work_date=date(2026, 10, 14),
            code='t4',
            done_by=self.user,
        )
        DayTaskDone.objects.filter(pk=first_legacy.pk).update(done_at=first_done)
        DayTaskDone.objects.filter(pk=second_legacy.pk).update(done_at=second_done)
        first = TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.WEEKLY,
            period_start=date(2026, 10, 12),
            period_end=date(2026, 10, 12),
            status=TaskOccurrence.Status.DONE,
            done_by=self.user,
            done_at=first_done,
            legacy_day_task_id=first_legacy.pk,
        )
        second = TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.WEEKLY,
            period_start=date(2026, 10, 14),
            period_end=date(2026, 10, 14),
            status=TaskOccurrence.Status.DONE,
            done_by=self.user,
            done_at=second_done,
            legacy_day_task_id=second_legacy.pk,
        )

        ensure_occurrences(self.org, today=date(2026, 10, 21), lookback_days=7)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.period_start, date(2026, 10, 12))
        self.assertEqual(first.period_end, date(2026, 10, 18))
        self.assertEqual(first.done_at, first_done)
        self.assertEqual(second.period_start, date(2026, 10, 14))
        self.assertEqual(second.period_end, date(2026, 10, 14))
        self.assertEqual(second.done_at, second_done)
        self.assertTrue(
            TaskOccurrence.objects.filter(organization_task=org_task, period_start=date(2026, 10, 19)).exists()
        )

    def test_disabled_event_and_auto_tasks_are_not_generated(self):
        daily = self.task('t1')
        daily.enabled = False
        daily.save()
        automatic = TaskDefinition.objects.create(
            code='auto-dnevno',
            title='Automatski pregled',
            kind=TaskDefinition.Kind.AUTO,
            cadence=TaskDefinition.Cadence.DAILY,
            auto_key='sensors_ok',
        )
        OrganizationTask.objects.create(
            organization=self.org,
            definition=automatic,
            enabled=True,
            active_from=self.ANCHOR,
        )
        self.only('t3', 't5', 'auto-dnevno')

        created = ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=3)
        self.assertEqual(created, 0)
        self.assertFalse(TaskOccurrence.objects.filter(organization=self.org).exists())

    def test_registration_assigns_catalog_for_the_industry(self):
        limited = TaskDefinition.objects.create(
            code='samo-proizvodnja',
            title='Samo proizvodnja',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.DAILY,
        )
        limited.industries.add(Industry.objects.get(code='proizvodnja'))
        form = RegistrationForm(data={
            'organization_name': 'Nova pekara',
            'industry': self.industry.pk,
            'first_name': 'Iva',
            'last_name': 'Vlasnik',
            'username': 'iva-nova',
            'email': 'iva@example.com',
            'password1': 'Sigurna-lozinka-1',
            'password2': 'Sigurna-lozinka-1',
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        codes = set(
            OrganizationTask.objects.filter(organization=user.organization)
            .values_list('definition__code', flat=True)
        )
        self.assertEqual(codes, {'t1', 't2', 't2w', 't2m', 't3', 't4', 't5'})
        self.assertFalse(TaskOccurrence.objects.filter(organization=user.organization).exists())
        self.assertEqual(assign_organization_tasks(user.organization), 0)
        self.assertEqual(user.organization.tasks_started_on, timezone.localdate())
        self.assertFalse(
            OrganizationTask.objects.filter(organization=user.organization)
            .exclude(active_from=user.organization.tasks_started_on)
            .exists()
        )
        self.assertFalse(
            OrganizationTask.objects.get(
                organization=user.organization,
                definition__code='t4',
            ).enabled
        )
        self.assertTrue(
            OrganizationTask.objects.get(
                organization=user.organization,
                definition__code='t2w',
            ).enabled
        )
