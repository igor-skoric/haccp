"""Podrazumevane stavke ček liste — OB-11 + UP-03."""

# SP = svakodnevno, NP = nedeljno, MP = mesečno (kao na papiru)
DEFAULT_LINES = (
    {
        'code': 'oprema',
        'label': 'Oprema za proizvodnju',
        'cadence': 'SP',
        'is_required': True,
        'sort_order': 10,
    },
    {
        'code': 'kanta',
        'label': 'Kanta za smeće',
        'cadence': 'SP',
        'is_required': True,
        'sort_order': 20,
    },
    {
        'code': 'povrsine',
        'label': 'Radne površine',
        'cadence': 'SP',
        'is_required': True,
        'sort_order': 30,
    },
    {
        'code': 'podovi',
        'label': 'Podovi i prolazi',
        'cadence': 'SP',
        'is_required': True,
        'sort_order': 40,
    },
    {
        'code': 'vitrine',
        'label': 'Vitrine / frižideri (spolja)',
        'cadence': 'SP',
        'is_required': True,
        'sort_order': 50,
    },
    {
        'code': 'hladnjaci',
        'label': 'Detaljno čišćenje rashladnih uređaja',
        'cadence': 'NP',
        'is_required': False,
        'sort_order': 60,
    },
    {
        'code': 'prostor',
        'label': 'Ceo prostor — generalno čišćenje',
        'cadence': 'MP',
        'is_required': False,
        'sort_order': 70,
    },
)


def seed_lines(record):
    from .models import HygieneLine

    HygieneLine.objects.bulk_create([
        HygieneLine(record=record, **item) for item in DEFAULT_LINES
    ])


def split_lines(check):
    """Razdeli stavke na svakodnevne (SP) i periodične (NP/MP)."""
    from .models import HygieneLine

    daily = []
    periodic = []
    for line in check.lines.all():
        if line.cadence == HygieneLine.Cadence.DAILY:
            daily.append(line)
        else:
            periodic.append(line)
    return daily, periodic


def required_progress_label(check):
    """Tekst napretka dnevnog OB-11 — samo obavezne (SP) stavke."""
    done = check.required_done_count
    total = check.required_total_count
    return f'{done} od {total} svakodnevnih kontrola'
