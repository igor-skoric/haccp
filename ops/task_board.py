"""Prikaz TaskOccurrence zapisa u obliku koji postojeći šabloni već crtaju."""

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from ops.hygiene import required_progress_label
from ops.models import GoodsReceipt, HygieneCheck, TaskDefinition, TaskOccurrence
from ops.nav import with_from
from ops.receiving import RECEIVING_KEY, active_receiving_task
from ops.scheduling import BELGRADE, ensure_occurrences, is_late


BACKLOG_PREVIEW = 3


def load_task_board(organization, today=None, *, from_key='today'):
    if today is None:
        today = timezone.localtime(timezone.now(), BELGRADE).date()
    empty = {
        'for_today': [],
        'hygiene_continue': None,
        'receiving': {
            'available': False,
            'open_count': 0,
            'open_url': '',
        },
        'open_receipts': [],
        'in_progress': [],
        'quick_actions': [],
        'backlog': [],
        'backlog_preview': [],
        'backlog_more': 0,
        'active': [],
        'completed': [],
        'missed': [],
        'current_open': [],
        'all': [],
        'receiving_available': False,
        'counts': {
            'todo': 0,
            'in_progress': 0,
            'open_receipts': 0,
            'missed': 0,
        },
    }
    if organization is None:
        return empty

    ensure_occurrences(organization, today=today)
    align_completed_hygiene(organization)
    occurrences = list(
        TaskOccurrence.objects
        .filter(organization=organization)
        .select_related(
            'organization_task__definition__document',
            'hygiene_check',
            'goods_receipt',
        )
        .prefetch_related('hygiene_check__lines')
        .order_by('organization_task__definition__sort_order', 'period_start', 'pk')
    )
    checks_by_date = {
        check.work_date: check
        for check in HygieneCheck.objects.filter(organization=organization).prefetch_related('lines')
    }
    open_hygiene_today = (
        HygieneCheck.objects
        .filter(
            organization=organization,
            work_date=today,
            status=HygieneCheck.Status.OPEN,
        )
        .prefetch_related('lines')
        .first()
    )
    open_receipts = list(
        GoodsReceipt.objects
        .filter(organization=organization, status=GoodsReceipt.Status.OPEN)
        .annotate(line_count=Count('lines'))
        .select_related('task_occurrence')
        .order_by('-received_on', '-pk')
    )

    rows = []
    for item in occurrences:
        if _open_legacy_duplicate(item, occurrences):
            continue
        # Isključeni zadaci: istorija DONE/MISSED ostaje, OPEN se ne nudi.
        if (
            item.status == TaskOccurrence.Status.OPEN
            and not item.organization_task.enabled
        ):
            continue
        definition = item.organization_task.definition
        # Periodični OB-11 (NP/MP) čekaju namenski complete — ne na dnevnoj tabli.
        if (
            definition.record_key == 'hygiene'
            and definition.hygiene_line_code
        ):
            continue
        rows.append(_present(
            item,
            today,
            checks_by_date.get(item.period_start),
            from_key=from_key,
        ))

    receiving_task = active_receiving_task(organization, today)
    receiving_available = receiving_task is not None

    for_today = []
    completed = []
    missed = []
    for row in rows:
        record_key = row.get('record_key')
        if row['status'] == TaskOccurrence.Status.DONE:
            completed.append(row)
            continue
        if row['status'] == TaskOccurrence.Status.MISSED:
            if row.get('cadence') != TaskDefinition.Cadence.EVENT:
                missed.append(row)
            continue
        if row['status'] != TaskOccurrence.Status.OPEN:
            continue
        if record_key == RECEIVING_KEY:
            continue
        if (
            record_key == 'hygiene'
            and row['current']
            and open_hygiene_today is not None
        ):
            continue
        if row['current']:
            for_today.append(row)

    hygiene_continue = None
    if open_hygiene_today is not None:
        hygiene_continue = _hygiene_in_progress_row(open_hygiene_today, from_key=from_key)

    open_receipt_rows = [
        _receipt_in_progress_row(receipt, from_key='receiving_open')
        for receipt in open_receipts
    ]
    receiving = {
        'available': receiving_available,
        'open_count': len(open_receipts),
        'open_url': with_from(reverse('receiving_open'), from_key),
        'from_key': from_key,
    }

    def _id_sort(row):
        value = row.get('receipt_pk') or row.get('evidence_pk') or row.get('id') or 0
        if isinstance(value, int):
            return value
        return 0

    for_today = sorted(for_today, key=lambda row: (row['sort'], _id_sort(row)))
    missed = sorted(missed, key=lambda row: row['period_start'], reverse=True)
    completed = sorted(
        completed,
        key=lambda row: (-row['period_start'].toordinal(), row['sort'], _id_sort(row)),
    )

    in_progress = [hygiene_continue] if hygiene_continue else []
    active = for_today + in_progress
    current_open = list(active)
    if receiving_available:
        current_open.append({'title': 'Novi prijem', 'section': 'quick_action'})

    return {
        'for_today': for_today,
        'hygiene_continue': hygiene_continue,
        'receiving': receiving,
        'open_receipts': open_receipt_rows,
        'in_progress': in_progress,
        'quick_actions': [],
        'backlog': missed,
        'backlog_preview': missed[:BACKLOG_PREVIEW],
        'backlog_more': max(0, len(missed) - BACKLOG_PREVIEW),
        'active': active,
        'completed': completed,
        'missed': missed,
        'current_open': current_open,
        'all': rows,
        'receiving_available': receiving_available,
        'counts': {
            'todo': len(for_today),
            'in_progress': len(in_progress),
            'open_receipts': len(open_receipts),
            'missed': len(missed),
        },
    }


def close_hygiene_task(check, user, when):
    """Zatvori pojavu koja pokriva ovaj OB-11. Ne dira već upisanog izvršioca."""
    occurrence = _hygiene_occurrence(check)
    if occurrence is None:
        return None
    if occurrence.status == TaskOccurrence.Status.DONE and occurrence.done_at is not None:
        if occurrence.hygiene_check_id is None:
            occurrence.hygiene_check = check
            occurrence.save(update_fields=['hygiene_check'])
        return occurrence
    occurrence.status = TaskOccurrence.Status.DONE
    occurrence.done_by = user
    occurrence.done_at = when
    occurrence.hygiene_check = check
    occurrence.save(update_fields=['status', 'done_by', 'done_at', 'hygiene_check'])
    return occurrence


def sync_hygiene_reopen(check, today=None):
    """Vrati pojavu na open samo dok njen period traje. Zatvoren period ostaje zapis."""
    if today is None:
        today = timezone.localtime(timezone.now(), BELGRADE).date()
    occurrence = _hygiene_occurrence(check)
    if occurrence is None:
        return None
    if not (occurrence.period_start <= today <= occurrence.period_end):
        return occurrence
    occurrence.status = TaskOccurrence.Status.OPEN
    occurrence.done_by = None
    occurrence.done_at = None
    occurrence.hygiene_check = check
    occurrence.save(update_fields=['status', 'done_by', 'done_at', 'hygiene_check'])
    return occurrence


def align_completed_hygiene(organization):
    """Ako OB-11 za taj period već ima završetak, pojava preuzima tog izvršioca."""
    rows = (
        TaskOccurrence.objects
        .filter(
            organization=organization,
            status__in=(TaskOccurrence.Status.OPEN, TaskOccurrence.Status.MISSED),
            organization_task__definition__record_key='hygiene',
            organization_task__definition__hygiene_line_code='',
        )
        .select_related('organization_task')
    )
    for occurrence in rows:
        check = (
            HygieneCheck.objects
            .filter(
                organization=organization,
                status=HygieneCheck.Status.DONE,
                completed_at__isnull=False,
                work_date__gte=occurrence.period_start,
                work_date__lte=occurrence.period_end,
            )
            .order_by('work_date')
            .first()
        )
        if check is None:
            continue
        occurrence.status = TaskOccurrence.Status.DONE
        occurrence.done_by = check.completed_by
        occurrence.done_at = check.completed_at
        occurrence.hygiene_check = check
        occurrence.save(update_fields=['status', 'done_by', 'done_at', 'hygiene_check'])


def _hygiene_occurrence(check):
    linked = (
        TaskOccurrence.objects
        .filter(organization=check.organization, hygiene_check=check)
        .order_by('period_start', 'pk')
        .first()
    )
    if linked is not None:
        return linked
    return (
        TaskOccurrence.objects
        .filter(
            organization=check.organization,
            organization_task__definition__record_key='hygiene',
            organization_task__definition__hygiene_line_code='',
            period_start__lte=check.work_date,
            period_end__gte=check.work_date,
        )
        .order_by('period_start', 'pk')
        .first()
    )


def _open_legacy_duplicate(item, occurrences):
    if item.status != TaskOccurrence.Status.OPEN or not item.legacy_day_task_id:
        return False
    if item.period_start != item.period_end:
        return False
    day = item.period_start
    for other in occurrences:
        if other.pk == item.pk or other.organization_task_id != item.organization_task_id:
            continue
        if other.period_start <= day <= other.period_end and other.period_start != other.period_end:
            return True
    return False


def _present(occurrence, today, check, *, from_key='today'):
    definition = occurrence.organization_task.definition
    current = occurrence.period_start <= today <= occurrence.period_end
    late = is_late(occurrence)
    overdue_open = (
        occurrence.status == TaskOccurrence.Status.OPEN
        and occurrence.due_at is not None
        and occurrence.due_at < timezone.now()
        and current
    )
    can_confirm = (
        definition.kind == TaskDefinition.Kind.CONFIRM
        and occurrence.status == TaskOccurrence.Status.OPEN
        and current
    )
    href = ''
    meta = _meta(definition, occurrence, check)
    if (
        definition.kind == TaskDefinition.Kind.RECORD
        and definition.record_key == 'hygiene'
        and not definition.hygiene_line_code
    ):
        href = _hygiene_href(occurrence, check, from_key=from_key)
    elif definition.kind == TaskDefinition.Kind.RECORD and definition.record_key == RECEIVING_KEY:
        href = _receiving_href(occurrence, from_key=from_key)
    if definition.kind != TaskDefinition.Kind.CONFIRM:
        can_confirm = False

    actionable = bool(href) or can_confirm
    return {
        'id': occurrence.pk,
        'title': definition.title,
        'meta': meta,
        'when': _when(occurrence, late),
        'done': occurrence.status == TaskOccurrence.Status.DONE,
        'status': occurrence.status,
        'current': current,
        'can_confirm': can_confirm,
        'can_create_receiving': False,
        'href': href,
        'priority': 'high' if occurrence.status == TaskOccurrence.Status.MISSED or late or overdue_open else 'normal',
        'mark': _mark(occurrence.status),
        'sort': definition.sort_order,
        'rank': _rank(occurrence.status),
        'period_start': occurrence.period_start,
        'period_end': occurrence.period_end,
        'kind': definition.kind,
        'record_key': definition.record_key,
        'hygiene_line_code': definition.hygiene_line_code,
        'cadence': occurrence.cadence or definition.cadence,
        'actionable': actionable,
        'section': 'task',
    }


def _hygiene_in_progress_row(check, *, from_key='today'):
    href = with_from(reverse('hygiene_detail', args=[check.pk]), from_key)
    return {
        'id': f'hygiene-{check.pk}',
        'title': 'Higijena radnog prostora',
        'meta': required_progress_label(check),
        'when': 'U toku',
        'action_label': 'Nastavi kontrolu',
        'done': False,
        'status': TaskOccurrence.Status.OPEN,
        'current': True,
        'can_confirm': False,
        'can_create_receiving': False,
        'href': href,
        'priority': 'normal',
        'mark': '…',
        'sort': 20,
        'rank': 0,
        'period_start': check.work_date,
        'period_end': check.work_date,
        'kind': TaskDefinition.Kind.RECORD,
        'record_key': 'hygiene',
        'cadence': TaskDefinition.Cadence.DAILY,
        'actionable': True,
        'section': 'in_progress',
        'evidence_pk': check.pk,
    }


def _receipt_in_progress_row(receipt, *, from_key='receiving_open'):
    line_count = getattr(receipt, 'line_count', None)
    if line_count is None:
        line_count = receipt.lines.count()
    href = with_from(reverse('receiving_detail', args=[receipt.pk]), from_key)
    return {
        'id': f'receipt-{receipt.pk}',
        'title': f'Prijem #{receipt.pk}',
        'meta': f'{line_count} stavki',
        'when': receipt.received_on.strftime('%d.%m.%Y.'),
        'done': False,
        'status': TaskOccurrence.Status.OPEN,
        'current': True,
        'can_confirm': False,
        'can_create_receiving': False,
        'href': href,
        'priority': 'normal',
        'mark': '…',
        'sort': 30,
        'rank': 0,
        'period_start': receipt.received_on,
        'period_end': receipt.received_on,
        'kind': TaskDefinition.Kind.RECORD,
        'record_key': RECEIVING_KEY,
        'cadence': TaskDefinition.Cadence.EVENT,
        'actionable': True,
        'section': 'open_receipt',
        'receipt_pk': receipt.pk,
        'line_count': line_count,
    }


def _meta(definition, occurrence, check):
    parts = []
    if definition.kind == TaskDefinition.Kind.RECORD and definition.record_key == 'hygiene':
        if definition.hygiene_line_code:
            parts.append('Periodična kontrola')
        elif check is not None and occurrence.status == TaskOccurrence.Status.OPEN:
            parts.append(required_progress_label(check))
        else:
            parts.append('Dnevna kontrola')
    elif definition.kind == TaskDefinition.Kind.RECORD and definition.record_key == RECEIVING_KEY:
        receipt = _linked_receipt(occurrence)
        if receipt is not None and occurrence.status == TaskOccurrence.Status.DONE:
            result = receipt.control_result()
            if result == TaskOccurrence.Result.PASSED:
                parts.append('Ispravno')
            elif result == TaskOccurrence.Result.FAILED:
                parts.append('Neispravno')
            else:
                parts.append('Završeno')
        else:
            parts.append('Prijem robe')
    elif definition.kind == TaskDefinition.Kind.CONFIRM:
        parts.append('Potvrda')
    if definition.kind == TaskDefinition.Kind.AUTO:
        parts.append('Automatski')
    elif (
        definition.kind == TaskDefinition.Kind.RECORD
        and definition.record_key not in {'hygiene', RECEIVING_KEY}
    ):
        parts.append('Unos još nije dostupan')
    return ' · '.join(parts)


def _hygiene_href(occurrence, check, *, from_key='today'):
    linked = occurrence.hygiene_check_id or (check.pk if check is not None else None)
    if linked:
        return with_from(reverse('hygiene_detail', args=[linked]), from_key)
    if occurrence.status == TaskOccurrence.Status.OPEN and occurrence.period_start == occurrence.period_end:
        return with_from(reverse('hygiene_today'), from_key)
    return ''


def _receiving_href(occurrence, *, from_key='today'):
    receipt = _linked_receipt(occurrence)
    if receipt is not None:
        return with_from(reverse('receiving_detail', args=[receipt.pk]), from_key)
    return with_from(reverse('receiving_list'), from_key)


def _linked_receipt(occurrence):
    try:
        return occurrence.goods_receipt
    except GoodsReceipt.DoesNotExist:
        return None


def _when(occurrence, late):
    due = _format_moment(occurrence.due_at) or occurrence.period_end.strftime('%d.%m.')
    if occurrence.status == TaskOccurrence.Status.MISSED:
        return f'Propušteno · {due}'
    if occurrence.status == TaskOccurrence.Status.DONE:
        done = _format_moment(occurrence.done_at) or due
        if late:
            return f'Kasno · {done}'
        return f'Završeno · {done}'
    if occurrence.due_at is not None and occurrence.due_at < timezone.now():
        return f'Kasni · {due}'
    return due


def _format_moment(value):
    if value is None:
        return ''
    local = timezone.localtime(value, BELGRADE)
    if local.hour == 23 and local.minute == 59:
        return local.strftime('%d.%m.')
    return local.strftime('%d.%m. %H:%M')


def _mark(status):
    if status == TaskOccurrence.Status.DONE:
        return '✓'
    if status == TaskOccurrence.Status.MISSED:
        return '!'
    return '○'


def _rank(status):
    if status == TaskOccurrence.Status.OPEN:
        return 0
    if status == TaskOccurrence.Status.MISSED:
        return 1
    return 2


def complete_task(occurrence, user, when):
    if occurrence.organization_task.definition.kind != TaskDefinition.Kind.CONFIRM:
        return False
    return TaskOccurrence.objects.filter(
        pk=occurrence.pk,
        organization_id=occurrence.organization_id,
        status=TaskOccurrence.Status.OPEN,
    ).update(
        status=TaskOccurrence.Status.DONE,
        done_by=user,
        done_at=when,
    ) == 1
