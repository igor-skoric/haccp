from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from ops.hygiene import seed_lines
from ops.hygiene_periodic import (
    MONTHLY_HYGIENE_CODE,
    T4_CODE,
    WEEKLY_HYGIENE_CODE,
    activate_periodic_hygiene_for_organization,
    ensure_periodic_hygiene_definitions,
)
from ops.models import HygieneCheck, HygieneLine, OrganizationTask, TaskDefinition, TaskOccurrence
from ops.scheduling import BELGRADE, assign_organization_tasks, ensure_occurrences
from ops.task_board import load_task_board
from organizations.models import Industry, Organization


class HygienePeriodicCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')

    def setUp(self):
        self.started = date(2026, 9, 1)
        self.cutover = date(2026, 10, 23)
        self.org = Organization.objects.create(
            name='Periodična A',
            industry=self.industry,
            tasks_started_on=self.started,
        )
        self.other = Organization.objects.create(
            name='Periodična B',
            industry=self.industry,
            tasks_started_on=self.started,
        )
        self.owner = User.objects.create_user(
            username='per-vlasnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.OWNER,
        )
        self.staff = User.objects.create_user(
            username='per-radnik',
            password='test-pass',
            organization=self.org,
            role=User.Role.STAFF,
        )
        # Stari katalog pre NP/MP dodele: t4 aktivan kao ranije
        ensure_periodic_hygiene_definitions()
        for code in ('t1', 't2', 't3', 't4', 't5'):
            definition = TaskDefinition.objects.get(code=code)
            OrganizationTask.objects.get_or_create(
                organization=self.org,
                definition=definition,
                defaults={'enabled': True, 'active_from': self.started},
            )
            OrganizationTask.objects.get_or_create(
                organization=self.other,
                definition=definition,
                defaults={'enabled': True, 'active_from': self.started},
            )
        # Otvori aktivacije za t4
        for org in (self.org, self.other):
            t4 = OrganizationTask.objects.get(organization=org, definition__code=T4_CODE)
            if not t4.activations.filter(ended_on__isnull=True).exists():
                t4.enabled = True
                t4.save()

    def test_definitions_assigned_with_line_codes(self):
        ensure_periodic_hygiene_definitions()
        weekly = TaskDefinition.objects.get(code=WEEKLY_HYGIENE_CODE)
        monthly = TaskDefinition.objects.get(code=MONTHLY_HYGIENE_CODE)
        self.assertEqual(weekly.kind, TaskDefinition.Kind.RECORD)
        self.assertEqual(weekly.cadence, TaskDefinition.Cadence.WEEKLY)
        self.assertEqual(weekly.record_key, 'hygiene')
        self.assertEqual(weekly.hygiene_line_code, 'hladnjaci')
        self.assertEqual(weekly.weekday, 4)
        self.assertEqual(weekly.document.code, 'OB-11')
        self.assertEqual(monthly.cadence, TaskDefinition.Cadence.MONTHLY)
        self.assertEqual(monthly.hygiene_line_code, 'prostor')
        self.assertEqual(monthly.monthday, 1)
        self.assertEqual(monthly.document.code, 'OB-11')

    def test_cutover_preserves_t4_history_and_avoids_overlap(self):
        t4 = OrganizationTask.objects.get(organization=self.org, definition__code=T4_CODE)
        with patch('ops.models.timezone.now', return_value=datetime(2026, 10, 16, 12, 0, tzinfo=BELGRADE)):
            ensure_occurrences(self.org, today=date(2026, 10, 16), lookback_days=40)
        historical = list(
            TaskOccurrence.objects.filter(organization_task=t4).values_list(
                'pk', 'status', 'period_start', 'period_end', 'done_by_id', 'done_at',
            )
        )
        self.assertTrue(historical)

        activate_periodic_hygiene_for_organization(self.org, on_date=self.cutover)
        t4.refresh_from_db()
        self.assertFalse(t4.enabled)
        window = t4.activations.order_by('-started_on').first()
        self.assertIsNotNone(window.ended_on)
        self.assertEqual(window.ended_on, self.cutover - timedelta(days=1))

        weekly = OrganizationTask.objects.get(
            organization=self.org,
            definition__code=WEEKLY_HYGIENE_CODE,
        )
        monthly = OrganizationTask.objects.get(
            organization=self.org,
            definition__code=MONTHLY_HYGIENE_CODE,
        )
        self.assertTrue(weekly.enabled)
        self.assertTrue(monthly.enabled)
        self.assertEqual(weekly.active_from, self.cutover)
        self.assertEqual(monthly.active_from, self.cutover)
        np_window = weekly.activations.filter(ended_on__isnull=True).get()
        self.assertEqual(np_window.started_on, self.cutover)
        self.assertGreater(np_window.started_on, window.ended_on)

        after = list(
            TaskOccurrence.objects.filter(organization_task=t4).values_list(
                'pk', 'status', 'period_start', 'period_end', 'done_by_id', 'done_at',
            )
        )
        self.assertEqual(historical, after)

    def test_no_duplicate_active_weekly_duties(self):
        activate_periodic_hygiene_for_organization(self.org, on_date=self.cutover)
        active_weekly = OrganizationTask.objects.filter(
            organization=self.org,
            enabled=True,
            definition__cadence=TaskDefinition.Cadence.WEEKLY,
        )
        self.assertEqual(active_weekly.count(), 1)
        self.assertEqual(active_weekly.get().definition.code, WEEKLY_HYGIENE_CODE)

    def test_activation_without_historical_missed_backlog(self):
        activate_periodic_hygiene_for_organization(self.org, on_date=self.cutover)
        ensure_occurrences(self.org, today=self.cutover, lookback_days=40)
        weekly = OrganizationTask.objects.get(
            organization=self.org,
            definition__code=WEEKLY_HYGIENE_CODE,
        )
        monthly = OrganizationTask.objects.get(
            organization=self.org,
            definition__code=MONTHLY_HYGIENE_CODE,
        )
        self.assertFalse(
            TaskOccurrence.objects.filter(
                organization_task=weekly,
                status=TaskOccurrence.Status.MISSED,
            ).exists()
        )
        self.assertFalse(
            TaskOccurrence.objects.filter(
                organization_task=monthly,
                status=TaskOccurrence.Status.MISSED,
            ).exists()
        )
        week = TaskOccurrence.objects.get(organization_task=weekly)
        self.assertEqual(week.period_start, date(2026, 10, 19))
        self.assertEqual(week.period_end, date(2026, 10, 25))
        self.assertEqual(week.status, TaskOccurrence.Status.OPEN)
        month = TaskOccurrence.objects.get(organization_task=monthly)
        self.assertEqual(month.period_start, date(2026, 10, 1))
        self.assertEqual(month.status, TaskOccurrence.Status.OPEN)

    def test_unique_weekly_and_monthly_occurrence(self):
        activate_periodic_hygiene_for_organization(self.org, on_date=self.cutover)
        ensure_occurrences(self.org, today=self.cutover, lookback_days=40)
        ensure_occurrences(self.org, today=self.cutover, lookback_days=40)
        self.assertEqual(
            TaskOccurrence.objects.filter(
                organization=self.org,
                organization_task__definition__code=WEEKLY_HYGIENE_CODE,
            ).count(),
            1,
        )
        self.assertEqual(
            TaskOccurrence.objects.filter(
                organization=self.org,
                organization_task__definition__code=MONTHLY_HYGIENE_CODE,
            ).count(),
            1,
        )

    def test_schedule_day_settings_on_organization_task(self):
        activate_periodic_hygiene_for_organization(self.org, on_date=self.cutover)
        weekly = OrganizationTask.objects.get(
            organization=self.org,
            definition__code=WEEKLY_HYGIENE_CODE,
        )
        monthly = OrganizationTask.objects.get(
            organization=self.org,
            definition__code=MONTHLY_HYGIENE_CODE,
        )
        weekly.weekday = 2
        weekly.save()
        monthly.monthday = 15
        monthly.save()
        ensure_occurrences(self.org, today=self.cutover, lookback_days=0)
        week = TaskOccurrence.objects.get(organization_task=weekly)
        self.assertEqual(
            week.due_at.astimezone(BELGRADE).date(),
            date(2026, 10, 21),
        )
        month = TaskOccurrence.objects.get(organization_task=monthly)
        self.assertEqual(
            month.due_at.astimezone(BELGRADE).date(),
            date(2026, 10, 15),
        )

    def test_new_org_gets_inactive_t4_and_active_np(self):
        org = Organization.objects.create(
            name='Novi objekat NP',
            industry=self.industry,
            tasks_started_on=self.cutover,
        )
        assign_organization_tasks(org, on_date=self.cutover)
        self.assertFalse(
            OrganizationTask.objects.get(organization=org, definition__code=T4_CODE).enabled
        )
        self.assertTrue(
            OrganizationTask.objects.get(
                organization=org,
                definition__code=WEEKLY_HYGIENE_CODE,
            ).enabled
        )
        self.assertTrue(
            OrganizationTask.objects.get(
                organization=org,
                definition__code=MONTHLY_HYGIENE_CODE,
            ).enabled
        )

    def test_daily_t2_and_hygiene_history_unchanged(self):
        check = HygieneCheck.objects.create(
            organization=self.org,
            work_date=self.cutover,
            created_by=self.staff,
        )
        seed_lines(check)
        snapshot = list(
            HygieneLine.objects.filter(record=check).order_by('pk').values_list(
                'code', 'cadence', 'is_required', 'is_done',
            )
        )
        t2_before = OrganizationTask.objects.get(organization=self.org, definition__code='t2')
        t2_enabled = t2_before.enabled
        t2_from = t2_before.active_from

        activate_periodic_hygiene_for_organization(self.org, on_date=self.cutover)
        t2_before.refresh_from_db()
        self.assertEqual(t2_before.enabled, t2_enabled)
        self.assertEqual(t2_before.active_from, t2_from)
        self.assertEqual(
            list(
                HygieneLine.objects.filter(record=check).order_by('pk').values_list(
                    'code', 'cadence', 'is_required', 'is_done',
                )
            ),
            snapshot,
        )

    def test_org_isolation_and_board_hides_periodic_until_complete_service(self):
        activate_periodic_hygiene_for_organization(self.org, on_date=self.cutover)
        activate_periodic_hygiene_for_organization(self.other, on_date=self.cutover)
        ensure_occurrences(self.org, today=self.cutover, lookback_days=40)
        ensure_occurrences(self.other, today=self.cutover, lookback_days=40)

        foreign = TaskOccurrence.objects.filter(
            organization=self.other,
            organization_task__definition__code=WEEKLY_HYGIENE_CODE,
        )
        self.assertTrue(foreign.exists())
        self.assertFalse(
            TaskOccurrence.objects.filter(
                organization=self.org,
                pk__in=foreign.values_list('pk', flat=True),
            ).exists()
        )

        board = load_task_board(self.org, today=self.cutover, from_key='today')
        titles = [row['title'] for row in board['for_today'] + board['backlog'] + board['completed']]
        self.assertNotIn('Nedeljna higijena rashladnih uređaja', titles)
        self.assertNotIn('Mesečna generalna higijena', titles)
        self.assertNotIn('Nedeljno čišćenje vitrina', titles)

        self.client.force_login(self.staff)
        home = self.client.get(reverse('today'))
        self.assertNotContains(home, 'Nedeljna higijena rashladnih')
        self.assertNotContains(home, 'Mesečna generalna higijena')
