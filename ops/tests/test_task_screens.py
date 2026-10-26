from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from ops.hygiene import seed_lines
from ops.models import DayTaskDone, HygieneCheck, OrganizationTask, TaskDefinition, TaskOccurrence
from ops.scheduling import BELGRADE, assign_organization_tasks
from organizations.models import Industry, Organization

NOW = datetime(2026, 10, 16, 8, 0, tzinfo=BELGRADE)


class TaskScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.get(code='kafic')
        cls.other = Industry.objects.get(code='proizvodnja')

    def setUp(self):
        self.org = Organization.objects.create(
            name='Ekran',
            industry=self.industry,
            tasks_started_on=NOW.date(),
        )
        self.other_org = Organization.objects.create(
            name='Drugi ekran',
            industry=self.other,
            tasks_started_on=NOW.date(),
        )
        self.staff = User.objects.create_user(
            username='ekran-radnik',
            password='test-pass',
            first_name='Mila',
            last_name='Radnik',
            organization=self.org,
            role=User.Role.STAFF,
        )
        self.other_staff = User.objects.create_user(
            username='drugi-radnik',
            password='test-pass',
            organization=self.other_org,
            role=User.Role.STAFF,
        )
        assign_organization_tasks(self.org, on_date=NOW.date())
        assign_organization_tasks(self.other_org, on_date=NOW.date())
        monthly = TaskDefinition.objects.create(
            code='mesecni-ekran',
            title='Mesečna kontrola',
            kind=TaskDefinition.Kind.CONFIRM,
            cadence=TaskDefinition.Cadence.MONTHLY,
            monthday=10,
        )
        OrganizationTask.objects.create(
            organization=self.org,
            definition=monthly,
            active_from=NOW.date(),
        )
        self.client.force_login(self.staff)

    def at_screen_time(self):
        return patch('ops.task_board.timezone.now', return_value=NOW)

    def open_task(self, code):
        return TaskOccurrence.objects.get(
            organization=self.org,
            organization_task__definition__code=code,
            status=TaskOccurrence.Status.OPEN,
            period_start__lte=NOW.date(),
            period_end__gte=NOW.date(),
        )

    def test_screens_list_real_periods_and_keep_history(self):
        with self.at_screen_time():
            home = self.client.get(reverse('today'))
            tasks = self.client.get(reverse('tasks'))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'Pregled temperatura vitrina')
        self.assertContains(home, 'Higijena radnog prostora')
        self.assertContains(home, 'Mesečna kontrola')
        # t4 je naslednikovan; NP/MP još nisu na tabli (čekaju complete servis)
        self.assertNotContains(home, 'Nedeljno čišćenje vitrina')
        self.assertNotContains(home, 'Nedeljna higijena rashladnih')
        self.assertNotContains(home, 'Mesečna generalna higijena')
        self.assertContains(home, 'csrfmiddlewaretoken')
        self.assertContains(home, reverse('hygiene_today'))
        self.assertContains(home, 'Zaostalo')
        self.assertEqual(home.context['missed_count'], 0)
        self.assertNotContains(home, 'Propušteno')
        self.assertNotContains(tasks, 'Propušteno')
        self.assertContains(tasks, 'Kasni')

        temperature = self.open_task('t1')
        with self.at_screen_time():
            done = self.client.post(reverse('task_done', args=[temperature.pk]), {'next': 'today'})
        self.assertEqual(done.status_code, 302)
        temperature.refresh_from_db()
        self.assertEqual(temperature.done_by, self.staff)
        self.assertIsNotNone(temperature.done_at)
        with self.at_screen_time():
            home_after = self.client.get(reverse('today'))
            tasks_after = self.client.get(reverse('tasks'))
        self.assertNotContains(home_after, reverse('task_done', args=[temperature.pk]))
        self.assertContains(tasks_after, 'Završeno')
        self.assertTrue(TaskOccurrence.objects.filter(pk=temperature.pk).exists())

    def test_repeat_confirm_keeps_the_original_actor(self):
        with self.at_screen_time():
            self.client.get(reverse('today'))
        occurrence = self.open_task('t1')
        with self.at_screen_time():
            self.client.post(reverse('task_done', args=[occurrence.pk]), {'next': 'tasks'})
        occurrence.refresh_from_db()
        actor = occurrence.done_by
        moment = occurrence.done_at
        with self.at_screen_time():
            again = self.client.post(reverse('task_done', args=[occurrence.pk]), {'next': 'tasks'})
        self.assertEqual(again.status_code, 302)
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.done_by, actor)
        self.assertEqual(occurrence.done_at, moment)

    def test_record_and_auto_cannot_be_confirmed(self):
        with self.at_screen_time():
            self.client.get(reverse('today'))
        hygiene = self.open_task('t2')
        denied = self.client.post(reverse('task_done', args=[hygiene.pk]), {'next': 'today'})
        self.assertEqual(denied.status_code, 403)
        hygiene.refresh_from_db()
        self.assertEqual(hygiene.status, TaskOccurrence.Status.OPEN)

        automatic = TaskDefinition.objects.create(
            code='auto-ekran',
            title='Automatski pregled',
            kind=TaskDefinition.Kind.AUTO,
            cadence=TaskDefinition.Cadence.DAILY,
            auto_key='sensors_ok',
        )
        org_task = OrganizationTask.objects.create(organization=self.org, definition=automatic)
        row = TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.DAILY,
            period_start=NOW.date(),
            period_end=NOW.date(),
            due_at=NOW,
            status=TaskOccurrence.Status.OPEN,
        )
        with self.at_screen_time():
            home = self.client.get(reverse('today'))
        self.assertContains(home, 'Automatski')
        self.assertNotContains(home, reverse('task_done', args=[row.pk]))
        self.assertEqual(self.client.post(reverse('task_done', args=[row.pk])).status_code, 403)
        row.refresh_from_db()
        self.assertEqual(row.status, TaskOccurrence.Status.OPEN)

    def test_hygiene_completion_and_reopen_follow_the_period(self):
        past_day = NOW.date() - timedelta(days=10)
        self.cover_from('t2', past_day)
        past_at = datetime(2026, 10, 6, 9, 0, tzinfo=BELGRADE)
        past_check = HygieneCheck.objects.create(
            organization=self.org,
            work_date=past_day,
            status=HygieneCheck.Status.DONE,
            created_by=self.staff,
            completed_by=self.staff,
            completed_at=past_at,
            note='stari dan',
        )
        with self.at_screen_time():
            self.client.get(reverse('today'))
        occurrence = self.open_task('t2')
        check = HygieneCheck.objects.create(
            organization=self.org,
            work_date=NOW.date(),
            created_by=self.staff,
        )
        seed_lines(check)
        payload = {'action': 'complete', 'note': 'gotovo'}
        for line in check.lines.filter(is_required=True):
            payload[f'line_{line.pk}'] = 'on'
        with self.at_screen_time():
            response = self.client.post(reverse('hygiene_detail', args=[check.pk]), payload)
        self.assertEqual(response.status_code, 302)
        occurrence.refresh_from_db()
        check.refresh_from_db()
        self.assertEqual(occurrence.status, TaskOccurrence.Status.DONE)
        self.assertEqual(occurrence.done_by, self.staff)
        self.assertEqual(occurrence.done_at, check.completed_at)
        self.assertEqual(occurrence.hygiene_check, check)

        with self.at_screen_time():
            self.client.post(reverse('hygiene_detail', args=[check.pk]), {'action': 'reopen'})
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, TaskOccurrence.Status.OPEN)
        self.assertIsNone(occurrence.done_at)

        past = TaskOccurrence.objects.get(
            organization=self.org,
            organization_task=occurrence.organization_task,
            period_start=past_day,
        )
        self.assertEqual(past.status, TaskOccurrence.Status.DONE)
        self.assertEqual(past.done_at, past_at)
        with self.at_screen_time():
            self.client.post(reverse('hygiene_detail', args=[past_check.pk]), {'action': 'reopen'})
        past.refresh_from_db()
        past_check.refresh_from_db()
        self.assertEqual(past.status, TaskOccurrence.Status.DONE)
        self.assertEqual(past.done_at, past_at)
        self.assertEqual(past.done_by, self.staff)
        self.assertEqual(past_check.note, 'stari dan')

    def test_other_organization_cannot_confirm(self):
        with self.at_screen_time():
            self.client.get(reverse('today'))
        occurrence = self.open_task('t1')
        self.client.force_login(self.other_staff)
        response = self.client.post(reverse('task_done', args=[occurrence.pk]), {'next': 'today'})
        self.assertEqual(response.status_code, 404)
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, TaskOccurrence.Status.OPEN)
        self.assertIsNone(occurrence.done_by)

    def cover_from(self, code, started_on):
        if self.org.tasks_started_on > started_on:
            self.org.tasks_started_on = started_on
            self.org.save(update_fields=['tasks_started_on'])
        org_task = OrganizationTask.objects.get(organization=self.org, definition__code=code)
        org_task.active_from = started_on
        org_task.save(update_fields=['active_from'])
        window = org_task.activations.get(ended_on__isnull=True)
        if window.started_on > started_on:
            window.started_on = started_on
            window.save(update_fields=['started_on'])

    def test_missed_and_late_labels_stay_distinct(self):
        self.cover_from('t1', NOW.date() - timedelta(days=1))
        with self.at_screen_time():
            home = self.client.get(reverse('today'))
        self.assertContains(home, 'Zaostalo')
        self.assertContains(home, 'Propušteno')
        missed = TaskOccurrence.objects.get(
            organization=self.org,
            organization_task__definition__code='t1',
            period_start=NOW.date() - timedelta(days=1),
        )
        self.assertEqual(missed.status, TaskOccurrence.Status.MISSED)
        self.assertNotContains(home, reverse('task_done', args=[missed.pk]))

        current = self.open_task('t1')
        late_at = datetime(2026, 10, 16, 11, 0, tzinfo=BELGRADE)
        TaskOccurrence.objects.filter(pk=current.pk).update(
            status=TaskOccurrence.Status.DONE,
            done_by=self.staff,
            done_at=late_at,
        )
        with self.at_screen_time():
            tasks = self.client.get(reverse('tasks'))
            home_after = self.client.get(reverse('today'))
        self.assertContains(tasks, 'Kasno')
        self.assertNotContains(home_after, reverse('task_done', args=[current.pk]))

    def test_unavailable_record_has_no_complete_button(self):
        definition = TaskDefinition.objects.create(
            code='record-nedostupan',
            title='Nepoznata evidencija',
            kind=TaskDefinition.Kind.RECORD,
            cadence=TaskDefinition.Cadence.EVENT,
            record_key='unknown_form',
        )
        org_task = OrganizationTask.objects.create(
            organization=self.org,
            definition=definition,
            active_from=NOW.date(),
        )
        row = TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.EVENT,
            period_start=NOW.date(),
            period_end=NOW.date(),
            status=TaskOccurrence.Status.OPEN,
            note='isporuka',
        )
        with self.at_screen_time():
            home = self.client.get(reverse('today'))
        self.assertContains(home, 'Unos još nije dostupan')
        self.assertNotContains(home, reverse('task_done', args=[row.pk]))
        self.assertEqual(self.client.post(reverse('task_done', args=[row.pk])).status_code, 403)

    def test_receiving_event_shows_without_occurrence(self):
        with self.at_screen_time():
            home = self.client.get(reverse('today'))
            tasks = self.client.get(reverse('tasks'))
        self.assertContains(home, 'Novi prijem')
        self.assertContains(home, 'Prijem sirovina')
        self.assertContains(home, reverse('receiving_create'))
        self.assertNotContains(home, 'Unos još nije dostupan')
        self.assertContains(tasks, 'Istorija prijema')

    def test_legacy_weekly_duplicates_do_not_become_two_open_tasks(self):
        org_task = OrganizationTask.objects.get(organization=self.org, definition__code='t4')
        if not org_task.enabled:
            org_task.enabled = True
            org_task.save()
            window = org_task.activations.filter(ended_on__isnull=True).first()
            if window is not None and window.started_on > org_task.active_from:
                window.started_on = org_task.active_from
                window.save(update_fields=['started_on'])
        first_at = datetime(2026, 10, 12, 8, 0, tzinfo=BELGRADE)
        second_at = datetime(2026, 10, 14, 8, 0, tzinfo=BELGRADE)
        first_legacy = DayTaskDone.objects.create(
            organization=self.org,
            work_date=first_at.date(),
            code='t4',
            done_by=self.staff,
        )
        second_legacy = DayTaskDone.objects.create(
            organization=self.org,
            work_date=second_at.date(),
            code='t4',
            done_by=self.staff,
        )
        DayTaskDone.objects.filter(pk=first_legacy.pk).update(done_at=first_at)
        DayTaskDone.objects.filter(pk=second_legacy.pk).update(done_at=second_at)
        TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.WEEKLY,
            period_start=first_at.date(),
            period_end=first_at.date(),
            status=TaskOccurrence.Status.DONE,
            done_by=self.staff,
            done_at=first_at,
            legacy_day_task_id=first_legacy.pk,
        )
        TaskOccurrence.objects.create(
            organization=self.org,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.WEEKLY,
            period_start=second_at.date(),
            period_end=second_at.date(),
            status=TaskOccurrence.Status.DONE,
            done_by=self.staff,
            done_at=second_at,
            legacy_day_task_id=second_legacy.pk,
        )
        later = datetime(2026, 10, 21, 8, 0, tzinfo=BELGRADE)
        with patch('ops.task_board.timezone.now', return_value=later):
            self.client.get(reverse('today'))
        open_rows = TaskOccurrence.objects.filter(
            organization=self.org,
            organization_task=org_task,
            status=TaskOccurrence.Status.OPEN,
        )
        self.assertEqual(open_rows.count(), 1)
        self.assertEqual(open_rows.get().period_start, datetime(2026, 10, 19).date())
        first_legacy.refresh_from_db()
        second_legacy.refresh_from_db()
        self.assertEqual(first_legacy.work_date, first_at.date())
        self.assertEqual(first_legacy.done_at, first_at)
        self.assertEqual(second_legacy.done_by, self.staff)
        historical = TaskOccurrence.objects.get(legacy_day_task_id=first_legacy.pk)
        self.assertEqual(historical.done_at, first_at)
        self.assertEqual(historical.status, TaskOccurrence.Status.DONE)
