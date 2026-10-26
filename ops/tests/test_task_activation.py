from datetime import date, datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.forms import RegistrationForm
from accounts.models import User
from ops.models import OrganizationTask, OrganizationTaskActivation, TaskDefinition, TaskOccurrence
from ops.scheduling import (
    BELGRADE,
    assign_organization_tasks,
    ensure_occurrences,
    review_missed_occurrences,
)
from organizations.models import Industry, Organization


class TaskActivationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def org(self, name, started):
        return Organization.objects.create(name=name, industry=self.industry, tasks_started_on=started)

    def test_new_organization_has_no_retroactive_misses(self):
        form = RegistrationForm(data={
            'organization_name': 'Nova aktivacija',
            'industry': self.industry.pk,
            'first_name': 'Iva',
            'last_name': 'Vlasnik',
            'username': 'iva-aktivacija',
            'email': 'iva-aktivacija@example.com',
            'password1': 'Sigurna-lozinka-1',
            'password2': 'Sigurna-lozinka-1',
        })
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        organization = user.organization
        started = organization.tasks_started_on
        self.assertEqual(started, timezone.localdate())
        ensure_occurrences(organization, today=started, lookback_days=35)
        self.assertFalse(
            TaskOccurrence.objects.filter(organization=organization, status=TaskOccurrence.Status.MISSED).exists()
        )
        self.assertFalse(
            TaskOccurrence.objects.filter(organization=organization, period_end__lt=started).exists()
        )
        current = TaskOccurrence.objects.get(
            organization=organization,
            organization_task__definition__code='t1',
        )
        self.assertEqual(current.period_start, started)
        self.assertEqual(current.status, TaskOccurrence.Status.OPEN)

    def test_existing_anchor_keeps_real_history_and_flags_invented_misses(self):
        started = date(2026, 10, 16)
        organization = self.org('Stari objekat', started)
        assign_organization_tasks(organization, on_date=started)
        task = OrganizationTask.objects.get(organization=organization, definition__code='t1')
        actor = User.objects.create_user(username='stari-izvrsilac', password='test-pass')
        done_at = datetime(2026, 10, 10, 9, 0, tzinfo=BELGRADE)
        done = TaskOccurrence.objects.create(
            organization=organization,
            organization_task=task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=date(2026, 10, 10),
            period_end=date(2026, 10, 10),
            status=TaskOccurrence.Status.DONE,
            done_by=actor,
            done_at=done_at,
        )
        invented = TaskOccurrence.objects.create(
            organization=organization,
            organization_task=task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=date(2026, 10, 9),
            period_end=date(2026, 10, 9),
            status=TaskOccurrence.Status.MISSED,
        )
        ensure_occurrences(organization, today=started, lookback_days=35)
        done.refresh_from_db()
        invented.refresh_from_db()
        self.assertEqual(done.status, TaskOccurrence.Status.DONE)
        self.assertEqual(done.done_by, actor)
        self.assertEqual(done.done_at, done_at)
        self.assertEqual(invented.status, TaskOccurrence.Status.MISSED)
        self.assertFalse(
            TaskOccurrence.objects.filter(
                organization=organization,
                organization_task=task,
                status=TaskOccurrence.Status.MISSED,
                period_start__lt=started,
            ).exclude(pk=invented.pk).exists()
        )
        flagged = review_missed_occurrences(organization)
        self.assertEqual([row.pk for row in flagged], [invented.pk])

    def test_new_task_on_an_old_organization_starts_on_its_own_day(self):
        organization = self.org('Objekat sa istorijom', date(2026, 9, 1))
        assign_organization_tasks(organization, on_date=date(2026, 9, 1))
        monthly = TaskDefinition.objects.create(
            code='kasnije-mesecno',
            title='Kasni mesečni',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.MONTHLY,
            monthday=10,
        )
        with patch('ops.scheduling.task_clock_date', return_value=date(2026, 10, 16)):
            created = assign_organization_tasks(organization)
        self.assertEqual(created, 1)
        org_task = OrganizationTask.objects.get(organization=organization, definition=monthly)
        self.assertEqual(org_task.active_from, date(2026, 10, 16))
        self.assertEqual(
            OrganizationTask.objects.get(organization=organization, definition__code='t1').active_from,
            date(2026, 9, 1),
        )
        ensure_occurrences(organization, today=date(2026, 10, 16), lookback_days=60)
        october = TaskOccurrence.objects.get(organization_task=org_task, period_start=date(2026, 10, 1))
        self.assertEqual(october.status, TaskOccurrence.Status.OPEN)
        self.assertFalse(
            TaskOccurrence.objects.filter(organization_task=org_task, period_start=date(2026, 9, 1)).exists()
        )

    def test_disabling_and_reenabling_skips_the_inactive_gap(self):
        organization = self.org('Pauza', date(2026, 10, 1))
        assign_organization_tasks(organization, on_date=date(2026, 10, 1))
        task = OrganizationTask.objects.get(organization=organization, definition__code='t1')
        actor = User.objects.create_user(username='pauza-izvrsilac', password='test-pass')
        done_at = datetime(2026, 10, 2, 8, 0, tzinfo=BELGRADE)
        TaskOccurrence.objects.create(
            organization=organization,
            organization_task=task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=date(2026, 10, 2),
            period_end=date(2026, 10, 2),
            status=TaskOccurrence.Status.DONE,
            done_by=actor,
            done_at=done_at,
        )
        ensure_occurrences(organization, today=date(2026, 10, 5), lookback_days=10)

        def at(day):
            return patch(
                'ops.models.timezone.now',
                return_value=datetime(2026, 10, day, 12, 0, tzinfo=BELGRADE),
            )

        task.enabled = False
        with at(10):
            task.save()
        task.refresh_from_db()
        closed = task.activations.get(ended_on__isnull=False)
        self.assertEqual(closed.ended_on, date(2026, 10, 10))

        task.enabled = True
        with at(20):
            task.save()
        opened = task.activations.get(ended_on__isnull=True)
        self.assertEqual(opened.started_on, date(2026, 10, 20))

        ensure_occurrences(organization, today=date(2026, 10, 20), lookback_days=35)
        for day in (date(2026, 10, 11), date(2026, 10, 15), date(2026, 10, 19)):
            self.assertFalse(
                TaskOccurrence.objects.filter(organization_task=task, period_start=day).exists(),
                day,
            )
        self.assertEqual(
            TaskOccurrence.objects.get(organization_task=task, period_start=date(2026, 10, 20)).status,
            TaskOccurrence.Status.OPEN,
        )
        kept = TaskOccurrence.objects.get(organization_task=task, period_start=date(2026, 10, 2))
        self.assertEqual(kept.status, TaskOccurrence.Status.DONE)
        self.assertEqual(kept.done_by, actor)
        self.assertEqual(kept.done_at, done_at)
        self.assertEqual(
            TaskOccurrence.objects.get(organization_task=task, period_start=date(2026, 10, 4)).status,
            TaskOccurrence.Status.MISSED,
        )

    def test_weekly_and_monthly_periods_before_activation_stay_open_or_absent(self):
        organization = self.org('Granice', date(2026, 10, 14))
        assign_organization_tasks(organization, on_date=date(2026, 10, 14))
        weekly = OrganizationTask.objects.get(organization=organization, definition__code='t2w')
        monthly = TaskDefinition.objects.create(
            code='granica-mesec',
            title='Granica meseca',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.MONTHLY,
            monthday=20,
        )
        OrganizationTask.objects.create(
            organization=organization,
            definition=monthly,
            active_from=date(2026, 10, 16),
        )
        ensure_occurrences(organization, today=date(2026, 10, 16), lookback_days=40)

        week = TaskOccurrence.objects.get(organization_task=weekly)
        self.assertEqual(week.period_start, date(2026, 10, 12))
        self.assertEqual(week.period_end, date(2026, 10, 18))
        self.assertEqual(week.status, TaskOccurrence.Status.OPEN)
        self.assertFalse(
            TaskOccurrence.objects.filter(organization_task=weekly, period_start=date(2026, 10, 5)).exists()
        )

        month = TaskOccurrence.objects.get(organization_task__definition=monthly)
        self.assertEqual(month.period_start, date(2026, 10, 1))
        self.assertEqual(month.status, TaskOccurrence.Status.OPEN)
        self.assertFalse(
            TaskOccurrence.objects.filter(
                organization_task__definition=monthly,
                period_start=date(2026, 9, 1),
            ).exists()
        )
        self.assertFalse(
            TaskOccurrence.objects.filter(
                organization=organization,
                status=TaskOccurrence.Status.MISSED,
                organization_task__in=(weekly, OrganizationTask.objects.get(definition=monthly)),
            ).exists()
        )

    def test_anchor_uses_the_task_date_not_the_organization_creation_date(self):
        organization = self.org('Kreiran ranije', date(2026, 10, 16))
        Organization.objects.filter(pk=organization.pk).update(
            created_at=datetime(2020, 1, 1, tzinfo=BELGRADE),
        )
        assign_organization_tasks(organization, on_date=date(2026, 10, 16))
        ensure_occurrences(organization, today=date(2026, 10, 16), lookback_days=35)
        organization.refresh_from_db()
        self.assertEqual(organization.tasks_started_on, date(2026, 10, 16))
        self.assertNotEqual(organization.tasks_started_on, organization.created_at.date())
        self.assertFalse(
            TaskOccurrence.objects.filter(organization=organization, period_end__lt=date(2026, 10, 16)).exists()
        )
        self.assertTrue(
            OrganizationTaskActivation.objects.filter(
                organization_task__organization=organization,
                started_on=date(2026, 10, 16),
                ended_on__isnull=True,
            ).exists()
        )
