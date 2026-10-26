"""Ručni unos temperatura (OB-10) i alerti iz stvarnih merenja."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import can_operate
from organizations.models import OrganizationSettings

from .models import ColdSpot, TemperatureReading, task_clock_date

DEFAULT_SPOTS = (
    ('Vitrina 1', 'Gornja polica', 10),
    ('Vitrina 1', 'Donja polica', 20),
    ('Vitrina 2', 'Gornja polica', 30),
    ('Vitrina 2', 'Donja polica', 40),
)


def ensure_cold_spots(organization):
    if organization is None:
        return []
    created = []
    for group_name, label, sort_order in DEFAULT_SPOTS:
        spot, was_created = ColdSpot.objects.get_or_create(
            organization=organization,
            group_name=group_name,
            label=label,
            defaults={'sort_order': sort_order, 'is_active': True},
        )
        if was_created:
            created.append(spot)
    return list(
        ColdSpot.objects.filter(organization=organization, is_active=True).order_by('sort_order', 'pk')
    )


def _limits(organization):
    min_c = Decimal('2.0')
    max_c = Decimal('8.0')
    alarms_enabled = True
    if organization is None:
        return min_c, max_c, alarms_enabled
    try:
        cfg = organization.settings
    except OrganizationSettings.DoesNotExist:
        return min_c, max_c, alarms_enabled
    return cfg.temp_min_c, cfg.temp_max_c, cfg.alarms_enabled


def record_temperature(organization, user, cold_spot, value_c, *, corrective_action='', when=None):
    if organization is None or not can_operate(user, organization):
        raise PermissionDenied('Nemaš pravo rada na ovom objektu.')
    if cold_spot.organization_id != organization.pk:
        raise ValidationError('Merna tačka ne pripada objektu.')
    if not cold_spot.is_active:
        raise ValidationError('Merna tačka nije aktivna.')

    moment = when or timezone.now()
    work_date = timezone.localtime(moment).date()
    min_c, max_c, _alarms = _limits(organization)
    value = Decimal(str(value_c))
    within = min_c <= value <= max_c
    note = (corrective_action or '').strip()

    with transaction.atomic():
        reading = TemperatureReading(
            organization=organization,
            cold_spot=cold_spot,
            work_date=work_date,
            value_c=value,
            min_c=min_c,
            max_c=max_c,
            is_within_limits=within,
            recorded_by=user,
            recorded_at=moment,
        )
        if note and not within:
            reading.corrective_action = note
            reading.corrective_by = user
            reading.corrective_at = moment
        reading.save()
        return reading


def add_corrective_action(organization, user, reading, action, *, when=None):
    if organization is None or not can_operate(user, organization):
        raise PermissionDenied('Nemaš pravo rada na ovom objektu.')
    if reading.organization_id != organization.pk:
        raise ValidationError('Merenje ne pripada objektu.')
    note = (action or '').strip()
    if not note:
        raise ValidationError({'corrective_action': 'Upiši korektivnu meru.'})
    if reading.is_within_limits:
        raise ValidationError('Korektivna mera važi samo za merenje van granica.')
    if (reading.corrective_action or '').strip():
        return reading

    moment = when or timezone.now()
    reading.corrective_action = note
    reading.corrective_by = user
    reading.corrective_at = moment
    reading.save()
    return reading


def sensor_cards(organization, today=None):
    day = today or task_clock_date()
    spots = ensure_cold_spots(organization)
    min_c, max_c, _alarms = _limits(organization)
    latest = {}
    rows = (
        TemperatureReading.objects
        .filter(organization=organization, work_date=day)
        .select_related('cold_spot')
        .order_by('cold_spot_id', '-recorded_at', '-pk')
    )
    for reading in rows:
        latest.setdefault(reading.cold_spot_id, reading)

    cards = []
    for spot in spots:
        reading = latest.get(spot.pk)
        if reading is None:
            cards.append({
                'id': spot.pk,
                'vitrine': spot.group_name,
                'label': spot.label,
                'temp': None,
                'unit': '°C',
                'min_c': float(min_c),
                'max_c': float(max_c),
                'status': 'missing',
                'updated': None,
                'reading': None,
            })
            continue
        status = 'ok' if reading.is_within_limits else 'alert'
        cards.append({
            'id': spot.pk,
            'vitrine': spot.group_name,
            'label': spot.label,
            'temp': float(reading.value_c),
            'unit': '°C',
            'min_c': float(reading.min_c),
            'max_c': float(reading.max_c),
            'status': status,
            'updated': reading.recorded_at,
            'reading': reading,
        })
    return cards


def open_alerts(organization, today=None):
    day = today or task_clock_date()
    _min_c, _max_c, alarms_enabled = _limits(organization)
    if not alarms_enabled:
        return []

    alerts = []
    open_readings = (
        TemperatureReading.objects
        .filter(
            organization=organization,
            work_date=day,
            is_within_limits=False,
            corrective_action='',
        )
        .select_related('cold_spot')
        .order_by('recorded_at')
    )
    for reading in open_readings:
        alerts.append({
            'id': f'reading-{reading.pk}',
            'reading_id': reading.pk,
            'level': 'critical',
            'title': 'Temperatura iznad granice' if reading.value_c > reading.max_c else 'Temperatura ispod granice',
            'detail': (
                f'{reading.cold_spot.group_name} · {reading.cold_spot.label} — '
                f'{reading.value_c} °C (granica {reading.min_c}–{reading.max_c} °C)'
            ),
            'since': reading.recorded_at,
            'action': 'Unesi korektivnu meru',
            'open': True,
            'can_correct': True,
        })

    for card in sensor_cards(organization, today=day):
        if card['status'] == 'missing':
            alerts.append({
                'id': f'missing-{card["id"]}',
                'reading_id': None,
                'level': 'warn',
                'title': 'Nema današnjeg merenja',
                'detail': f'{card["vitrine"]} · {card["label"]}',
                'since': timezone.now(),
                'action': 'Unesi temperaturu na stranici Temperature',
                'open': True,
                'can_correct': False,
            })

    closed = (
        TemperatureReading.objects
        .filter(
            organization=organization,
            work_date=day,
            is_within_limits=False,
        )
        .exclude(corrective_action='')
        .select_related('cold_spot', 'corrective_by')
        .order_by('-corrective_at')[:10]
    )
    for reading in closed:
        alerts.append({
            'id': f'closed-{reading.pk}',
            'reading_id': reading.pk,
            'level': 'info',
            'title': 'Urađena korektivna mera',
            'detail': (
                f'{reading.cold_spot.group_name} · {reading.cold_spot.label} — '
                f'{reading.value_c} °C · {reading.corrective_action}'
            ),
            'since': reading.corrective_at or reading.recorded_at,
            'action': '',
            'open': False,
            'can_correct': False,
        })

    return alerts


def recent_history(organization, spot=None, limit=12):
    qs = (
        TemperatureReading.objects
        .filter(organization=organization)
        .select_related('cold_spot')
        .order_by('-recorded_at')
    )
    if spot is not None:
        qs = qs.filter(cold_spot=spot)
    rows = list(qs[:limit])
    rows.reverse()
    history = []
    for reading in rows:
        history.append({
            'at': reading.recorded_at,
            'temp': float(reading.value_c),
            'hot': not reading.is_within_limits,
            'bar': min(100, max(12, round((float(reading.value_c) / 12) * 100))),
            'label': f'{reading.cold_spot.group_name} · {reading.cold_spot.label}',
        })
    return history


def measured_today_count(organization, today=None):
    day = today or task_clock_date()
    spots = ensure_cold_spots(organization)
    if not spots:
        return 0, 0
    measured = (
        TemperatureReading.objects
        .filter(organization=organization, work_date=day, cold_spot__in=spots)
        .values('cold_spot_id')
        .distinct()
        .count()
    )
    return measured, len(spots)
