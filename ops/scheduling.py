"""Raspored periodičnih obaveza.

ensure_occurrences pozivaju ekrani koji prikazuju zadatke.
Nema pozadinskog rada.

Pojava nastaje samo za dane u kojima su i objekat i obaveza bili aktivni.
Period koji je počeo pre aktivacije ne postaje propušten.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from ops.models import OrganizationTask, TaskDefinition, TaskOccurrence, task_clock_date

BELGRADE = ZoneInfo('Europe/Belgrade')
LOOKBACK_DAYS = 35
END_OF_DAY = time(23, 59, 59)
PERIODIC = (
    TaskDefinition.Cadence.DAILY,
    TaskDefinition.Cadence.WEEKLY,
    TaskDefinition.Cadence.MONTHLY,
)
# Prazno dok ne postoji stvarna provera senzora ili alarma.
IMPLEMENTED_AUTO_KEYS = frozenset()


def assign_organization_tasks(organization, *, on_date=None):
    """Napravi nedostajuća podešavanja objekta iz kataloga koji važi za njegovu delatnost.

    Nova obaveza važi od dana dodele. Ako objekat još nema početak, taj dan postaje i njegov.
    Postojeći zadatak zadržava svoj datum.
    t4 se novim objektima dodeljuje isključen — naslednik je t2w.
    """
    from ops.hygiene_periodic import default_enabled_for_definition, ensure_periodic_hygiene_definitions

    ensure_periodic_hygiene_definitions()
    if organization.tasks_started_on is None:
        organization.tasks_started_on = on_date or task_clock_date()
        organization.save(update_fields=['tasks_started_on'])
    assignment_day = on_date or task_clock_date()
    definitions = TaskDefinition.objects.filter(is_active=True).order_by('sort_order', 'code')
    created = 0
    for definition in definitions:
        if not definition.applies_to_industry(organization.industry):
            continue
        _task, was_created = OrganizationTask.objects.get_or_create(
            organization=organization,
            definition=definition,
            defaults={
                'enabled': default_enabled_for_definition(definition),
                'active_from': assignment_day,
            },
        )
        if was_created:
            created += 1
    return created


def ensure_occurrences(organization, *, today=None, lookback_days=LOOKBACK_DAYS):
    """Dopuni periodične pojave jednog objekta i zatvori istekle otvorene periode.

    Događajni zadaci i automatske provere bez integracije se ne prave.
    Postojeći due_at, done_at i done_by se ne diraju.
    Propuštena pojava nastaje samo kad je ceo period bio pokriven aktivacijom
    i kad je počeo na dan aktivacije objekta i obaveze ili posle njega.
    """
    if today is None:
        today = timezone.localtime(timezone.now(), BELGRADE).date()
    created = 0
    with transaction.atomic():
        normalize_legacy_weekly(organization)
        tasks = (
            OrganizationTask.objects
            .filter(organization=organization, enabled=True, definition__is_active=True)
            .select_related('definition')
            .order_by('definition__sort_order', 'definition__code', 'pk')
        )
        for org_task in tasks:
            if not _generates(org_task):
                continue
            activations = list(org_task.activations.all())
            floor = _floor(organization, org_task, today)
            _close_expired(organization, org_task, today, floor, activations)
            schedule = _schedule(org_task)
            for period in _periods(schedule, today, lookback_days):
                if _find_occurrence(organization, org_task, period['period_start']) is not None:
                    continue
                status = _status_for_period(period, today, floor, activations)
                if status is None:
                    continue
                _row, was_created = _save_new_occurrence(
                    organization=organization,
                    organization_task=org_task,
                    cadence=schedule['cadence'],
                    period_start=period['period_start'],
                    period_end=period['period_end'],
                    due_at=period['due_at'],
                    status=status,
                )
                if was_created:
                    created += 1
    return created


def review_missed_occurrences(organization=None):
    """Propuštene pojave koje današnja pravila ne bi sama napravila.

    Ne briše zapise i ne menja izvršioca. Istorijski prenos iz DayTaskDone
    nije sumnjiv: taj zapis je stvarni završetak, čak i ako mu je status kasnije diran.
    """
    rows = (
        TaskOccurrence.objects
        .filter(status=TaskOccurrence.Status.MISSED, legacy_day_task_id__isnull=True)
        .select_related('organization', 'organization_task__definition')
        .prefetch_related('organization_task__activations')
        .order_by('organization_id', 'period_start', 'pk')
    )
    if organization is not None:
        rows = rows.filter(organization=organization)
    suspicious = []
    for row in rows:
        activations = list(row.organization_task.activations.all())
        floor = _floor(row.organization, row.organization_task, row.period_end)
        period = {
            'period_start': row.period_start,
            'period_end': row.period_end,
        }
        owed = _status_for_period(
            period,
            row.period_end + timedelta(days=1),
            floor,
            activations,
        )
        if owed != TaskOccurrence.Status.MISSED:
            suspicious.append(row)
    return suspicious


def is_late(occurrence):
    """Zakašnjenje nije status. Vidi se samo kad postoje i rok i vreme završetka."""
    if occurrence.done_at is None or occurrence.due_at is None:
        return False
    return occurrence.done_at > occurrence.due_at


def normalize_legacy_weekly(organization):
    """Preneti t4 ima period od jednog dana. Poravnaj ga na tu nedelju, bez novih podataka.

    done_at i done_by ostaju. Ako je kanonski ponedeljak već zauzet, jednodnevni
    zapis ostaje na svom datumu i ne blokira drugu nedelju.
    """
    rows = (
        TaskOccurrence.objects
        .filter(
            organization=organization,
            legacy_day_task_id__isnull=False,
            cadence=TaskDefinition.Cadence.WEEKLY,
            period_start=F('period_end'),
        )
        .order_by('legacy_day_task_id', 'pk')
    )
    for row in rows:
        monday = _week_monday(row.period_start)
        sunday = monday + timedelta(days=6)
        if row.period_start == monday and row.period_end == sunday:
            continue
        taken = (
            TaskOccurrence.objects
            .filter(
                organization=row.organization_id,
                organization_task=row.organization_task_id,
                period_start=monday,
                cadence=TaskDefinition.Cadence.WEEKLY,
            )
            .exclude(pk=row.pk)
            .exists()
        )
        if taken:
            continue
        row.period_start = monday
        row.period_end = sunday
        row.save(update_fields=['period_start', 'period_end'])


def _generates(org_task):
    definition = org_task.definition
    if definition.cadence not in PERIODIC:
        return False
    if definition.kind == TaskDefinition.Kind.AUTO and definition.auto_key not in IMPLEMENTED_AUTO_KEYS:
        return False
    return True


def _floor(organization, org_task, today):
    started = organization.tasks_started_on or today
    active = org_task.active_from or today
    return max(started, active)


def _close_expired(organization, org_task, today, floor, activations):
    rows = TaskOccurrence.objects.filter(
        organization=organization,
        organization_task=org_task,
        cadence__in=PERIODIC,
        status=TaskOccurrence.Status.OPEN,
        period_end__lt=today,
    )
    for row in rows:
        period = {'period_start': row.period_start, 'period_end': row.period_end}
        if _status_for_period(period, today, floor, activations) != TaskOccurrence.Status.MISSED:
            continue
        TaskOccurrence.objects.filter(pk=row.pk, status=TaskOccurrence.Status.OPEN).update(
            status=TaskOccurrence.Status.MISSED,
        )


def _status_for_period(period, today, floor, activations):
    start = period['period_start']
    end = period['period_end']
    if end < floor:
        return None
    if _period_fully_active(start, end, floor, activations):
        if end < today:
            return TaskOccurrence.Status.MISSED
        return TaskOccurrence.Status.OPEN
    if end >= today and today >= floor and start <= today and _day_covered(today, activations):
        return TaskOccurrence.Status.OPEN
    return None


def _period_fully_active(start, end, floor, activations):
    if start < floor:
        return False
    day = start
    while day <= end:
        if not _day_covered(day, activations):
            return False
        day += timedelta(days=1)
    return True


def _day_covered(day, activations):
    for span in activations:
        if span.started_on <= day and (span.ended_on is None or day <= span.ended_on):
            return True
    return False


def _schedule(org_task):
    definition = org_task.definition
    return {
        'cadence': definition.cadence,
        'weekday': definition.weekday if org_task.weekday is None else org_task.weekday,
        'monthday': definition.monthday if org_task.monthday is None else org_task.monthday,
        'due_time': definition.due_time if org_task.due_time is None else org_task.due_time,
    }


def _periods(schedule, today, lookback_days):
    window_start = today - timedelta(days=lookback_days)
    cadence = schedule['cadence']
    if cadence == TaskDefinition.Cadence.DAILY:
        day = window_start
        while day <= today:
            yield _daily_period(day, schedule['due_time'])
            day += timedelta(days=1)
        return
    if cadence == TaskDefinition.Cadence.WEEKLY:
        monday = _week_monday(window_start)
        while monday <= today:
            yield _weekly_period(monday, schedule['weekday'], schedule['due_time'])
            monday += timedelta(days=7)
        return
    if cadence == TaskDefinition.Cadence.MONTHLY:
        year, month = window_start.year, window_start.month
        while date(year, month, 1) <= date(today.year, today.month, 1):
            yield _monthly_period(year, month, schedule['monthday'], schedule['due_time'])
            year, month = _next_month(year, month)


def _daily_period(day, due_time):
    return {
        'period_start': day,
        'period_end': day,
        'due_at': _at(day, due_time),
    }


def _weekly_period(monday, weekday, due_time):
    due_day = monday + timedelta(days=weekday)
    return {
        'period_start': monday,
        'period_end': monday + timedelta(days=6),
        'due_at': _at(due_day, due_time),
    }


def _monthly_period(year, month, monthday, due_time):
    last_day = _last_day(year, month)
    return {
        'period_start': date(year, month, 1),
        'period_end': date(year, month, last_day),
        'due_at': _at(date(year, month, monthday), due_time),
    }


def _find_occurrence(organization, org_task, period_start):
    return (
        TaskOccurrence.objects
        .filter(
            organization=organization,
            organization_task=org_task,
            period_start=period_start,
            cadence__in=PERIODIC,
        )
        .first()
    )


def _save_new_occurrence(**fields):
    try:
        with transaction.atomic():
            return TaskOccurrence.objects.create(**fields), True
    except (IntegrityError, ValidationError) as exc:
        existing = _find_occurrence(
            fields['organization'],
            fields['organization_task'],
            fields['period_start'],
        )
        if existing is None:
            raise exc
        return existing, False


def _at(day, clock):
    return timezone.make_aware(datetime.combine(day, clock or END_OF_DAY), BELGRADE)


def _week_monday(day):
    return day - timedelta(days=day.weekday())


def _last_day(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _next_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1
