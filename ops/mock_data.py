"""Privremeni mock podaci za UI prototip. Kasnije: baza + IoT."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Belgrade')


def _now():
    return datetime.now(TZ)


def sensors(min_c=2.0, max_c=8.0):
    """Poslastičarnica: 2 vitrine × 2 senzora."""
    now = _now()
    points = [
        ('v1-a', 'Vitrina 1', 'Gornja polica', 4.8, 2),
        ('v1-b', 'Vitrina 1', 'Donja polica', 5.1, 2),
        ('v2-a', 'Vitrina 2', 'Gornja polica', 9.4, 1),
        ('v2-b', 'Vitrina 2', 'Donja polica', 6.2, 1),
    ]
    rows = []
    for sensor_id, vitrine, label, temp, minutes_ago in points:
        rows.append({
            'id': sensor_id,
            'vitrine': vitrine,
            'label': label,
            'temp': temp,
            'unit': '°C',
            'min_c': min_c,
            'max_c': max_c,
            'status': 'ok' if min_c <= temp <= max_c else 'alert',
            'updated': now - timedelta(minutes=minutes_ago),
        })
    return rows


def alerts(max_c=8.0, stale_minutes=10, alarms_enabled=True):
    now = _now()
    temp_open = alarms_enabled and 9.4 > max_c
    stale_open = alarms_enabled and 12 > stale_minutes
    return [
        {
            'id': 'a1',
            'level': 'critical',
            'title': 'Temperatura iznad granice',
            'detail': f'Vitrina 2 · Gornja polica — 9.4 °C (max {max_c:.1f} °C)',
            'since': now - timedelta(minutes=18),
            'action': 'Proveri vrata / prebaci proizvode · unesi korektivnu meru',
            'open': temp_open,
        },
        {
            'id': 'a2',
            'level': 'warn',
            'title': 'Senzor kasni',
            'detail': 'Vitrina 1 · Donja polica — poslednje očitanje pre 12 min',
            'since': now - timedelta(minutes=12),
            'action': 'Proveri uređaj; ako treba unesi ručno merenje',
            'open': stale_open,
        },
        {
            'id': 'a3',
            'level': 'info',
            'title': 'Urađena korektivna mera',
            'detail': 'Vitrina 2 · juče 21:40 — proizvodi prebačeni, T vraćena na 5.6 °C',
            'since': now - timedelta(hours=22),
            'action': '',
            'open': False,
        },
    ]


def tasks():
    return [
        {
            'id': 't1',
            'title': 'Pregled temperatura vitrina',
            'meta': '4 senzora · OB-10',
            'when': 'Danas · do 10:00',
            'done': False,
            'priority': 'high',
        },
        {
            'id': 't2',
            'title': 'Higijena radnog prostora',
            'meta': 'Ček lista · OB-11',
            'when': 'Danas · po smeni',
            'done': False,
            'priority': 'normal',
        },
        {
            'id': 't3',
            'title': 'Prijem sirovina',
            'meta': 'Ako ima isporuke · OB-15',
            'when': 'Po dolasku',
            'done': False,
            'priority': 'normal',
        },
        {
            'id': 't4',
            'title': 'Nedeljno čišćenje vitrina',
            'meta': 'UP-03 · detaljno',
            'when': 'Ova nedelja · petak',
            'done': False,
            'priority': 'low',
        },
        {
            'id': 't5',
            'title': 'Reši otvoren alert',
            'meta': 'Vitrina 2 · korektivna mera',
            'when': 'Hitno',
            'done': False,
            'priority': 'high',
        },
    ]


def recent_readings(sensor_id='v2-a'):
    now = _now()
    base = 5.2 if sensor_id != 'v2-a' else 7.8
    points = []
    for i in range(12, 0, -1):
        bump = 1.6 if sensor_id == 'v2-a' and i <= 4 else 0
        points.append({
            'at': now - timedelta(minutes=5 * i),
            'temp': round(base + bump + (i % 3) * 0.15, 1),
        })
    return points
