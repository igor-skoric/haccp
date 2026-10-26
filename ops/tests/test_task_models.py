from datetime import datetime
from zoneinfo import ZoneInfo

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from ops.hygiene import seed_lines
from ops.models import DayTaskDone, HygieneCheck, OrganizationTask, TaskDefinition, TaskOccurrence
from ops.task_catalog import migrate_day_tasks, seed_task_catalog
from organizations.models import Industry, Organization

TZ = ZoneInfo('Europe/Belgrade')


class TaskModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')
        cls.other = Industry.objects.get(code='proizvodnja')
        cls.org_a = Organization.objects.create(name='Objekat A', industry=cls.industry)
        cls.org_b = Organization.objects.create(name='Objekat B', industry=cls.other)
        cls.user = User.objects.create_user(
            username='izvrsilac',
            password='test-pass',
            first_name='Mila',
            last_name='Radnik',
            organization=cls.org_a,
            role=User.Role.STAFF,
        )
        seed_task_catalog(apps)

    def test_catalog_matches_mock_tasks_without_fake_completions(self):
        definitions = TaskDefinition.objects.filter(
            code__in=['t1', 't2', 't2w', 't2m', 't3', 't4', 't5'],
        )
        self.assertEqual(definitions.count(), 7)
        by_code = {item.code: item for item in definitions}
        self.assertEqual(by_code['t1'].kind, TaskDefinition.Kind.CONFIRM)
        self.assertEqual(by_code['t1'].cadence, TaskDefinition.Cadence.DAILY)
        self.assertEqual(by_code['t1'].due_time.strftime('%H:%M'), '10:00')
        self.assertEqual(by_code['t1'].document.code, 'OB-10')
        self.assertEqual(by_code['t2'].record_key, 'hygiene')
        self.assertEqual(by_code['t2'].hygiene_line_code, '')
        self.assertEqual(by_code['t2'].document.code, 'OB-11')
        self.assertEqual(by_code['t2w'].cadence, TaskDefinition.Cadence.WEEKLY)
        self.assertEqual(by_code['t2w'].hygiene_line_code, 'hladnjaci')
        self.assertEqual(by_code['t2w'].weekday, 4)
        self.assertEqual(by_code['t2m'].cadence, TaskDefinition.Cadence.MONTHLY)
        self.assertEqual(by_code['t2m'].hygiene_line_code, 'prostor')
        self.assertEqual(by_code['t2m'].monthday, 1)
        self.assertEqual(by_code['t3'].cadence, TaskDefinition.Cadence.EVENT)
        self.assertEqual(by_code['t3'].record_key, 'receiving')
        self.assertEqual(by_code['t4'].weekday, 4)
        self.assertEqual(by_code['t4'].document.code, 'UP-03')
        self.assertEqual(by_code['t5'].kind, TaskDefinition.Kind.AUTO)
        self.assertEqual(by_code['t5'].auto_key, 'open_alert')
        self.assertFalse(TaskOccurrence.objects.filter(legacy_day_task_id__isnull=True, status=TaskOccurrence.Status.DONE).exists())
        self.assertTrue(by_code['t1'].applies_to_industry(self.industry))
        self.assertTrue(by_code['t1'].applies_to_industry(self.other))

    def test_empty_industry_list_can_be_narrowed(self):
        definition = TaskDefinition.objects.get(code='t1')
        definition.industries.add(self.industry)
        self.assertTrue(definition.applies_to_industry(self.industry))
        self.assertFalse(definition.applies_to_industry(self.other))
        definition.industries.clear()

    def test_schedule_fields_follow_cadence(self):
        with self.assertRaises(ValidationError):
            TaskDefinition.objects.create(
                code='lose-nedeljno',
                title='Bez dana',
                kind=TaskDefinition.Kind.CONFIRM,
                cadence=TaskDefinition.Cadence.WEEKLY,
            )
        with self.assertRaises(ValidationError):
            TaskDefinition.objects.create(
                code='lose-mesecno',
                title='Dan 31',
                kind=TaskDefinition.Kind.CONFIRM,
                cadence=TaskDefinition.Cadence.MONTHLY,
                monthday=31,
            )
        monthly = TaskDefinition.objects.create(
            code='mesecni',
            title='Mesečni pregled',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.MONTHLY,
            monthday=15,
        )
        org_task = OrganizationTask.objects.create(organization=self.org_a, definition=monthly)
        org_task.weekday = 1
        with self.assertRaises(ValidationError):
            org_task.save()

    def test_periodic_occurrence_is_unique_per_period(self):
        org_task = OrganizationTask.objects.get(
            organization=self.org_a,
            definition__code='t1',
        )
        TaskOccurrence.objects.create(
            organization=self.org_a,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start='2026-10-16',
            period_end='2026-10-16',
            status=TaskOccurrence.Status.OPEN,
        )
        with self.assertRaises(ValidationError):
            TaskOccurrence.objects.create(
                organization=self.org_a,
                organization_task=org_task,
                cadence=TaskDefinition.Cadence.DAILY,
                period_start='2026-10-16',
                period_end='2026-10-16',
                status=TaskOccurrence.Status.OPEN,
            )
        self.assertEqual(
            TaskOccurrence.objects.filter(
                organization=self.org_a,
                organization_task=org_task,
            ).count(),
            1,
        )
        TaskOccurrence.objects.create(
            organization=self.org_a,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start='2026-10-17',
            period_end='2026-10-17',
            status=TaskOccurrence.Status.OPEN,
        )
        other = OrganizationTask.objects.get(organization=self.org_b, definition__code='t1')
        TaskOccurrence.objects.create(
            organization=self.org_b,
            organization_task=other,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start='2026-10-16',
            period_end='2026-10-16',
            status=TaskOccurrence.Status.OPEN,
        )

    def test_events_allow_several_on_the_same_day(self):
        org_task = OrganizationTask.objects.get(
            organization=self.org_a,
            definition__code='t3',
        )
        first = TaskOccurrence.objects.create(
            organization=self.org_a,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.EVENT,
            period_start='2026-10-16',
            period_end='2026-10-16',
            status=TaskOccurrence.Status.OPEN,
            note='jutarnji prijem',
        )
        second = TaskOccurrence.objects.create(
            organization=self.org_a,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.EVENT,
            period_start='2026-10-16',
            period_end='2026-10-16',
            status=TaskOccurrence.Status.OPEN,
            note='popodnevni prijem',
        )
        self.assertNotEqual(first.pk, second.pk)

    def test_failed_result_stays_a_completed_check(self):
        org_task = OrganizationTask.objects.get(
            organization=self.org_a,
            definition__code='t1',
        )
        occurrence = TaskOccurrence.objects.create(
            organization=self.org_a,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start='2026-10-18',
            period_end='2026-10-18',
            status=TaskOccurrence.Status.DONE,
            done_by=self.user,
            done_at=timezone.now(),
            result=TaskOccurrence.Result.FAILED,
        )
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, TaskOccurrence.Status.DONE)
        self.assertEqual(occurrence.result, TaskOccurrence.Result.FAILED)

    def test_occurrence_cannot_cross_organizations(self):
        foreign = OrganizationTask.objects.get(
            organization=self.org_b,
            definition__code='t1',
        )
        with self.assertRaises(ValidationError):
            TaskOccurrence.objects.create(
                organization=self.org_a,
                organization_task=foreign,
                cadence=TaskDefinition.Cadence.DAILY,
                period_start='2026-10-16',
                period_end='2026-10-16',
                status=TaskOccurrence.Status.OPEN,
            )
        check = HygieneCheck.objects.create(
            organization=self.org_b,
            work_date='2026-10-16',
            created_by=self.user,
        )
        own = OrganizationTask.objects.get(organization=self.org_a, definition__code='t2')
        with self.assertRaises(ValidationError):
            TaskOccurrence.objects.create(
                organization=self.org_a,
                organization_task=own,
                cadence=TaskDefinition.Cadence.DAILY,
                period_start='2026-10-19',
                period_end='2026-10-19',
                status=TaskOccurrence.Status.OPEN,
                hygiene_check=check,
            )

    def test_day_task_history_is_copied_once_and_hygiene_stays(self):
        done_at = datetime(2026, 10, 1, 8, 30, tzinfo=TZ)
        legacy = DayTaskDone.objects.create(
            organization=self.org_a,
            work_date=done_at.date(),
            code='t1',
            done_by=self.user,
        )
        DayTaskDone.objects.filter(pk=legacy.pk).update(done_at=done_at)
        legacy.refresh_from_db()
        unknown = DayTaskDone.objects.create(
            organization=self.org_b,
            work_date=done_at.date(),
            code='stari-kod',
            done_by=None,
        )
        check = HygieneCheck.objects.create(
            organization=self.org_a,
            work_date=done_at.date(),
            created_by=self.user,
            note='istorija',
            status=HygieneCheck.Status.DONE,
            completed_by=self.user,
            completed_at=done_at,
        )
        seed_lines(check)
        line_snapshot = list(check.lines.values_list('code', 'cadence', 'is_done', 'done_by_id'))

        migrate_day_tasks(apps)
        migrate_day_tasks(apps)

        copied = TaskOccurrence.objects.get(legacy_day_task_id=legacy.pk)
        self.assertEqual(copied.organization, self.org_a)
        self.assertEqual(copied.organization_task.definition.code, 't1')
        self.assertEqual(copied.status, TaskOccurrence.Status.DONE)
        self.assertEqual(copied.done_by, self.user)
        self.assertEqual(copied.done_at, done_at)
        self.assertIsNone(copied.result)
        self.assertIsNone(copied.hygiene_check)
        self.assertEqual(TaskOccurrence.objects.filter(legacy_day_task_id=legacy.pk).count(), 1)

        other = TaskOccurrence.objects.get(legacy_day_task_id=unknown.pk)
        self.assertEqual(other.organization, self.org_b)
        self.assertEqual(other.organization_task.definition.code, 'stari-kod')
        self.assertFalse(
            TaskOccurrence.objects.filter(organization=self.org_a, legacy_day_task_id=unknown.pk).exists()
        )

        check.refresh_from_db()
        self.assertEqual(check.work_date, done_at.date())
        self.assertEqual(check.note, 'istorija')
        self.assertEqual(check.status, HygieneCheck.Status.DONE)
        self.assertEqual(check.completed_by, self.user)
        self.assertEqual(check.completed_at, done_at)
        self.assertEqual(
            list(check.lines.values_list('code', 'cadence', 'is_done', 'done_by_id')),
            line_snapshot,
        )
        self.assertEqual(DayTaskDone.objects.filter(pk__in=[legacy.pk, unknown.pk]).count(), 2)

    def test_seed_can_run_again_without_duplicating_the_catalog(self):
        seed_task_catalog(apps)
        self.assertEqual(TaskDefinition.objects.filter(code='t2').count(), 1)
        self.assertEqual(
            OrganizationTask.objects.filter(organization=self.org_a, definition__code='t4').count(),
            1,
        )
