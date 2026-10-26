"""Katalog zadataka i prenos postojećih DayTaskDone redova.

Ova etapa ne pravi nove pojave i ne menja higijenu. Prenosi samo stvarne
završetke iz DayTaskDone.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Belgrade')

CATALOG = (
    {
        'code': 't1',
        'title': 'Pregled temperatura vitrina',
        'kind': 'confirm',
        'cadence': 'daily',
        'weekday': None,
        'monthday': None,
        'due_time': datetime.strptime('10:00', '%H:%M').time(),
        'document_code': 'OB-10',
        'record_key': '',
        'hygiene_line_code': '',
        'auto_key': '',
        'sort_order': 10,
    },
    {
        'code': 't2',
        'title': 'Higijena radnog prostora',
        'kind': 'record',
        'cadence': 'daily',
        'weekday': None,
        'monthday': None,
        'due_time': None,
        'document_code': 'OB-11',
        'record_key': 'hygiene',
        'hygiene_line_code': '',
        'auto_key': '',
        'sort_order': 20,
    },
    {
        'code': 't2w',
        'title': 'Nedeljna higijena rashladnih uređaja',
        'kind': 'record',
        'cadence': 'weekly',
        'weekday': 4,
        'monthday': None,
        'due_time': None,
        'document_code': 'OB-11',
        'record_key': 'hygiene',
        'hygiene_line_code': 'hladnjaci',
        'auto_key': '',
        'sort_order': 24,
    },
    {
        'code': 't2m',
        'title': 'Mesečna generalna higijena',
        'kind': 'record',
        'cadence': 'monthly',
        'weekday': None,
        'monthday': 1,
        'due_time': None,
        'document_code': 'OB-11',
        'record_key': 'hygiene',
        'hygiene_line_code': 'prostor',
        'auto_key': '',
        'sort_order': 26,
    },
    {
        'code': 't3',
        'title': 'Prijem sirovina',
        'kind': 'record',
        'cadence': 'event',
        'weekday': None,
        'monthday': None,
        'due_time': None,
        'document_code': 'OB-15',
        'record_key': 'receiving',
        'hygiene_line_code': '',
        'auto_key': '',
        'sort_order': 30,
    },
    {
        'code': 't4',
        'title': 'Nedeljno čišćenje vitrina',
        'kind': 'confirm',
        'cadence': 'weekly',
        'weekday': 4,
        'monthday': None,
        'due_time': None,
        'document_code': 'UP-03',
        'record_key': '',
        'hygiene_line_code': '',
        'auto_key': '',
        'sort_order': 40,
    },
    {
        'code': 't5',
        'title': 'Reši otvoren alert',
        'kind': 'auto',
        'cadence': 'event',
        'weekday': None,
        'monthday': None,
        'due_time': None,
        'document_code': '',
        'record_key': '',
        'hygiene_line_code': '',
        'auto_key': 'open_alert',
        'sort_order': 50,
    },
)


def seed_task_catalog(apps):
    TaskDefinition = apps.get_model('ops', 'TaskDefinition')
    Organization = apps.get_model('organizations', 'Organization')
    OrganizationTask = apps.get_model('ops', 'OrganizationTask')
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')

    for item in CATALOG:
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

    definitions = list(TaskDefinition.objects.filter(code__in=[item['code'] for item in CATALOG]))
    for organization in Organization.objects.order_by('pk'):
        for definition in definitions:
            OrganizationTask.objects.get_or_create(
                organization=organization,
                definition=definition,
                defaults={
                    'enabled': definition.code != 't4',
                },
            )


def migrate_day_tasks(apps):
    DayTaskDone = apps.get_model('ops', 'DayTaskDone')
    TaskDefinition = apps.get_model('ops', 'TaskDefinition')
    OrganizationTask = apps.get_model('ops', 'OrganizationTask')
    TaskOccurrence = apps.get_model('ops', 'TaskOccurrence')

    rows = DayTaskDone.objects.select_related('organization', 'done_by').order_by('pk')
    for row in rows:
        if TaskOccurrence.objects.filter(legacy_day_task_id=row.pk).exists():
            continue
        definition = _definition_for_code(TaskDefinition, row.code)
        organization_task, _created = OrganizationTask.objects.get_or_create(
            organization=row.organization,
            definition=definition,
            defaults={'enabled': True},
        )
        due_at = None
        if definition.due_time is not None:
            due_at = datetime.combine(row.work_date, definition.due_time, tzinfo=TZ)
        TaskOccurrence.objects.create(
            organization=row.organization,
            organization_task=organization_task,
            cadence=definition.cadence,
            period_start=row.work_date,
            period_end=row.work_date,
            due_at=due_at,
            status='done',
            done_by=row.done_by,
            done_at=row.done_at,
            result=None,
            note='',
            hygiene_check=None,
            legacy_day_task_id=row.pk,
        )


def _definition_for_code(TaskDefinition, code):
    definition = TaskDefinition.objects.filter(code=code).first()
    if definition is not None:
        return definition
    definition, _created = TaskDefinition.objects.get_or_create(
        code=code,
        defaults={
            'title': code,
            'kind': 'confirm',
            'cadence': 'daily',
            'weekday': None,
            'monthday': None,
            'due_time': None,
            'record_key': '',
            'hygiene_line_code': '',
            'auto_key': '',
            'sort_order': 900,
            'is_active': True,
        },
    )
    return definition
