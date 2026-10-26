"""Katalog i aktivacija periodičnih OB-11 obaveza (NP/MP).

t2w nasledjuje stari t4 confirm. Izvršenje NP/MP nije u ovoj etapi.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ops.models import OrganizationTask, TaskDefinition, task_clock_date
from ops.task_catalog import CATALOG

WEEKLY_HYGIENE_CODE = 't2w'
MONTHLY_HYGIENE_CODE = 't2m'
T4_CODE = 't4'
T4_SUCCESSOR_CODE = WEEKLY_HYGIENE_CODE
PERIODIC_HYGIENE_CODES = (WEEKLY_HYGIENE_CODE, MONTHLY_HYGIENE_CODE)


def catalog_item(code):
    for item in CATALOG:
        if item['code'] == code:
            return item
    raise KeyError(code)


def ensure_periodic_hygiene_definitions():
    """Idempotentno upiše t2w/t2m u katalog (živi modeli)."""
    from documents.models import DocumentTemplate

    for code in PERIODIC_HYGIENE_CODES:
        item = catalog_item(code)
        document = None
        if item['document_code']:
            document = DocumentTemplate.objects.filter(code=item['document_code']).first()
        TaskDefinition.objects.update_or_create(
            code=item['code'],
            defaults={
                'title': item['title'],
                'kind': item['kind'],
                'cadence': item['cadence'],
                'weekday': item['weekday'],
                'monthday': item['monthday'],
                'due_time': item['due_time'],
                'document': document,
                'record_key': item['record_key'],
                'hygiene_line_code': item['hygiene_line_code'],
                'auto_key': item['auto_key'],
                'sort_order': item['sort_order'],
                'is_active': True,
            },
        )


def default_enabled_for_definition(definition):
    """t4 je naslednikovan t2w-om — nove dodele ne dobijaju aktivan t4."""
    if definition.code == T4_CODE:
        return False
    return True


def activate_periodic_hygiene_for_organization(organization, *, on_date=None):
    """Uključi NP/MP od on_date i povuci t4 bez preklapanja aktivacija.

    Ne dira DONE/MISSED pojave. OPEN pojave t4 ostaju u bazi; tabla ih
    ne prikazuje dok je t4 isključen.
    """
    if on_date is None:
        on_date = task_clock_date()
    ensure_periodic_hygiene_definitions()
    with transaction.atomic():
        _retire_t4(organization, on_date)
        _activate_periodic(organization, WEEKLY_HYGIENE_CODE, on_date)
        _activate_periodic(organization, MONTHLY_HYGIENE_CODE, on_date)


def _retire_t4(organization, on_date):
    org_task = (
        OrganizationTask.objects
        .filter(organization=organization, definition__code=T4_CODE)
        .select_related('definition')
        .first()
    )
    if org_task is None:
        return
    window = (
        org_task.activations
        .filter(ended_on__isnull=True)
        .order_by('started_on')
        .first()
    )
    if window is not None:
        end = on_date - timedelta(days=1)
        if end < window.started_on:
            end = window.started_on
        window.ended_on = end
        window.save(update_fields=['ended_on'])
    if org_task.enabled:
        org_task.enabled = False
        org_task.save()


def _activate_periodic(organization, code, on_date):
    definition = TaskDefinition.objects.get(code=code)
    org_task, created = OrganizationTask.objects.get_or_create(
        organization=organization,
        definition=definition,
        defaults={
            'enabled': True,
            'active_from': on_date,
        },
    )
    if created:
        return org_task
    fields = []
    if org_task.active_from != on_date and not org_task.enabled:
        org_task.active_from = on_date
        fields.append('active_from')
    elif org_task.active_from is None:
        org_task.active_from = on_date
        fields.append('active_from')
    if not org_task.enabled:
        if fields:
            org_task.save(update_fields=fields)
            fields = []
        org_task.enabled = True
        org_task.save()
        # save() otvara aktivaciju od "today"; poravnaj na on_date ako treba
        window = (
            org_task.activations
            .filter(ended_on__isnull=True)
            .order_by('-started_on')
            .first()
        )
        if window is not None and window.started_on != on_date:
            window.started_on = on_date
            window.save(update_fields=['started_on'])
    elif fields:
        org_task.save(update_fields=fields)
    return org_task


def activation_windows(organization, code):
    org_task = OrganizationTask.objects.filter(
        organization=organization,
        definition__code=code,
    ).first()
    if org_task is None:
        return []
    return list(org_task.activations.order_by('started_on', 'pk'))
