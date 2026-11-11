def is_checklist(document) -> bool:
    return bool((getattr(document, 'checklist', None) or {}).get('items'))


def question_items(checklist):
    return [
        item for item in (checklist or {}).get('items', [])
        if item.get('type') == 'q'
    ]


def clean_answers(checklist, posted):
    allowed = {option['value'] for option in (checklist or {}).get('scale', [])}
    cleaned = {}
    for item in question_items(checklist):
        value = (posted.get(f"q_{item['key']}") or '').strip()
        if value in allowed:
            cleaned[item['key']] = value
    return cleaned


def clean_notes(checklist, posted):
    notes = {}
    for item in question_items(checklist):
        text = (posted.get(f"n_{item['key']}") or '').strip()
        if text:
            notes[item['key']] = text
    return notes


def progress_counts(checklist, answers):
    keys = [item['key'] for item in question_items(checklist)]
    done = sum(1 for key in keys if (answers or {}).get(key))
    return done, len(keys)


def is_complete(checklist, answers):
    done, total = progress_counts(checklist, answers)
    return total > 0 and done == total


def finished_label(count):
    if count % 10 == 1 and count % 100 != 11:
        word = 'završena'
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = 'završene'
    else:
        word = 'završenih'
    return f'{count} {word}'


def annotate_progress(documents, tenant):
    if tenant is None:
        return
    from .models import InspectionRecord

    records = (
        InspectionRecord.objects.filter(
            organization=tenant,
            template__in=documents,
        )
        .order_by('-created_at', '-pk')
    )
    open_runs = {}
    done_counts = {}
    for record in records:
        if record.status == InspectionRecord.Status.OPEN:
            open_runs.setdefault(record.template_id, record)
        else:
            done_counts[record.template_id] = done_counts.get(record.template_id, 0) + 1
    templates = {document.pk: document for document in documents}
    for template_id, record in open_runs.items():
        document = templates[template_id]
        done, total = progress_counts(record.snapshot or document.checklist, record.answers)
        document.progress_label = f'U toku {done}/{total}'
    for template_id, count in done_counts.items():
        if template_id in open_runs:
            continue
        templates[template_id].progress_label = finished_label(count)


def present_run(document, record, *, tenant, writable):
    checklist = record.snapshot or document.checklist or {}
    answers = record.answers or {}
    notes = record.notes or {}
    groups = []
    current = {'title': '', 'items': [], 'answered': 0, 'total': 0, 'open': False}
    number = 0
    for item in checklist.get('items', []):
        if item.get('type') == 'section':
            if current['title'] or current['items']:
                groups.append(current)
            current = {
                'title': item.get('text', ''),
                'items': [],
                'answered': 0,
                'total': 0,
                'open': False,
            }
            continue
        if item.get('type') != 'q':
            continue
        number += 1
        answer = answers.get(item['key'], '')
        current['items'].append({
            'key': item['key'],
            'n': number,
            'text': item.get('text', ''),
            'answer': answer,
            'note': notes.get(item['key'], ''),
        })
        current['total'] += 1
        if answer:
            current['answered'] += 1
    if current['title'] or current['items']:
        groups.append(current)
    opened = False
    for group in groups:
        if group['title'] and not opened and group['answered'] < group['total']:
            group['open'] = True
            opened = True
    if groups and not opened and groups[0]['title']:
        groups[0]['open'] = True
    total = number
    done = sum(group['answered'] for group in groups)
    return {
        'mode': 'run',
        'folded': any(group['title'] for group in groups),
        'groups': groups,
        'scale': checklist.get('scale', []),
        'answered': done,
        'total': total,
        'percent': round(100 * done / total) if total else 0,
        'writable': writable,
        'subject': tenant.name if tenant else '',
        'remarks': record.remarks,
        'choice_count': len(checklist.get('scale', [])),
    }
