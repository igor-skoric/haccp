"""Servis evidencije OB-15 — Prijem sirovina.

Svaki prijem dobija sopstvenu događajnu pojavu zadatka.
Završeni zapisi ostaju neizmenljivi.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from accounts.permissions import can_configure, can_operate
from ops.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    OrganizationTask,
    TaskDefinition,
    TaskOccurrence,
    task_clock_date,
)
from ops.scheduling import BELGRADE

RECEIVING_KEY = 'receiving'
LINE_FIELDS = (
    'raw_material',
    'manufacturer',
    'quantity',
    'visual_check',
    'product_safety',
    'note',
    'sort_order',
)


def create_goods_receipt(organization, user, *, received_on=None):
    """Otvori novi list prijema i događajnu pojavu u istoj transakciji."""
    _require_operate(user, organization)
    day = received_on or task_clock_date()
    org_task = _active_receiving_task(organization, day)
    if org_task is None:
        raise ValidationError('Prijem sirovina nije aktivan za ovaj objekat.')

    with transaction.atomic():
        occurrence = TaskOccurrence(
            organization=organization,
            organization_task=org_task,
            cadence=TaskDefinition.Cadence.EVENT,
            period_start=day,
            period_end=day,
            status=TaskOccurrence.Status.OPEN,
        )
        occurrence.save()
        receipt = GoodsReceipt(
            organization=organization,
            received_on=day,
            created_by=user,
            task_occurrence=occurrence,
        )
        receipt.save()
    return receipt


def add_goods_receipt_line(organization, user, receipt, **fields):
    """Dodaj potpunu stavku na otvoren prijem."""
    receipt = _open_receipt(organization, user, receipt)
    data = _validated_line_fields(fields, require_complete=True)
    if 'sort_order' not in data:
        last = receipt.lines.order_by('-sort_order').values_list('sort_order', flat=True).first()
        data['sort_order'] = 0 if last is None else last + 1
    line = GoodsReceiptLine(goods_receipt=receipt, **data)
    line.save()
    return line


def update_goods_receipt_line(organization, user, line, **fields):
    """Izmeni stavku dok je prijem otvoren."""
    line = _line_for(organization, user, line)
    if line.goods_receipt.status != GoodsReceipt.Status.OPEN:
        raise ValidationError('Stavka završenog prijema se ne menja.')
    merged = {
        'raw_material': line.raw_material,
        'manufacturer': line.manufacturer,
        'quantity': line.quantity,
        'visual_check': line.visual_check,
        'product_safety': line.product_safety,
        'note': line.note,
        'sort_order': line.sort_order,
    }
    merged.update(fields)
    data = _validated_line_fields(merged, require_complete=True)
    for name, value in data.items():
        setattr(line, name, value)
    line.save()
    return line


def delete_goods_receipt_line(organization, user, line):
    """Obriši stavku sa otvorenog prijema."""
    line = _line_for(organization, user, line)
    if line.goods_receipt.status != GoodsReceipt.Status.OPEN:
        raise ValidationError('Stavka završenog prijema se ne briše.')
    line.delete()


def complete_goods_receipt(organization, user, receipt, *, when=None):
    """Završi prijem i povezanu pojavu. Ponovljeni poziv čuva prvog izvršioca."""
    _require_operate(user, organization)
    moment = when or timezone.now()
    receipt_id = receipt.pk if hasattr(receipt, 'pk') else receipt

    with transaction.atomic():
        locked = _lock_receipt(receipt_id, organization)
        if locked.status == GoodsReceipt.Status.DONE:
            return locked
        if locked.status == GoodsReceipt.Status.CANCELLED:
            raise ValidationError('Otkazan prijem se ne završava.')

        if locked.task_occurrence_id is None:
            raise ValidationError('Prijem mora imati povezanu pojavu zadatka.')

        lines = list(locked.lines.all())
        if not lines or any(not item.is_complete() for item in lines):
            raise ValidationError('Završen prijem mora imati potpuno popunjene stavke.')

        result = locked.control_result()
        if result is None:
            raise ValidationError('Završen prijem mora imati potpuno popunjene stavke.')

        locked.status = GoodsReceipt.Status.DONE
        locked.completed_by = user
        locked.completed_at = moment
        locked.save()

        occurrence = _lock_occurrence(locked.task_occurrence_id, organization)
        if occurrence.status == TaskOccurrence.Status.OPEN:
            occurrence.status = TaskOccurrence.Status.DONE
            occurrence.done_by = user
            occurrence.done_at = moment
            occurrence.result = result
            occurrence.save()
        elif occurrence.result is None:
            occurrence.result = result
            occurrence.save()
        return locked


def cancel_goods_receipt(organization, user, receipt, *, reason='', when=None):
    """Otkaži otvoren prijem. Ne briše zapis i ne računa se kao izvršen zadatak."""
    _require_operate(user, organization)
    moment = when or timezone.now()
    receipt_id = receipt.pk if hasattr(receipt, 'pk') else receipt
    text = (reason or '').strip()
    if len(text) > 255:
        raise ValidationError({'cancellation_reason': 'Razlog je predugačak (max 255).'})

    with transaction.atomic():
        locked = _lock_receipt(receipt_id, organization)
        if locked.status == GoodsReceipt.Status.CANCELLED:
            return locked
        if locked.status != GoodsReceipt.Status.OPEN:
            raise ValidationError('Samo otvoren prijem se može otkazati.')

        locked.status = GoodsReceipt.Status.CANCELLED
        locked.cancelled_by = user
        locked.cancelled_at = moment
        locked.cancellation_reason = text
        locked.save()

        if locked.task_occurrence_id is not None:
            occurrence = _lock_occurrence(locked.task_occurrence_id, organization)
            if occurrence.status != TaskOccurrence.Status.CANCELLED:
                occurrence.status = TaskOccurrence.Status.CANCELLED
                occurrence.done_by = None
                occurrence.done_at = None
                occurrence.result = None
                occurrence.save()
        return locked


def verify_goods_receipt(organization, user, receipt, *, verifier_role, when=None):
    """Upis verifikacije završenog prijema. Ne menja ishod kontrole."""
    if not can_configure(user, organization):
        raise PermissionDenied('Nemaš pravo verifikacije na ovom objektu.')
    moment = when or timezone.now()
    role = (verifier_role or '').strip()
    if not role:
        raise ValidationError({'verifier_role': 'Upiši funkciju verifikatora.'})

    receipt_id = receipt.pk if hasattr(receipt, 'pk') else receipt
    with transaction.atomic():
        locked = _lock_receipt(receipt_id, organization)
        if locked.status == GoodsReceipt.Status.CANCELLED:
            raise ValidationError('Otkazan prijem se ne verifikuje.')
        if locked.status != GoodsReceipt.Status.DONE:
            raise ValidationError('Verifikacija važi samo za završen prijem.')
        if locked._verification_complete():
            return locked
        if locked.completed_by_id == user.pk:
            raise ValidationError('Izvršilac ne može da verifikuje sopstveni prijem.')

        locked.verified_by = user
        locked.verified_on = timezone.localtime(moment, BELGRADE).date()
        locked.verified_at = moment
        locked.verifier_role = role
        locked.save()
        return locked


def _require_operate(user, organization):
    if organization is None or not can_operate(user, organization):
        raise PermissionDenied('Nemaš pravo rada na ovom objektu.')


def active_receiving_task(organization, on_date=None):
    """Aktivan OrganizationTask za receiving na dati dan, ili None."""
    day = on_date or task_clock_date()
    return _active_receiving_task(organization, day)


def _active_receiving_task(organization, on_date):
    task = (
        OrganizationTask.objects
        .filter(
            organization=organization,
            enabled=True,
            definition__is_active=True,
            definition__record_key=RECEIVING_KEY,
            definition__kind=TaskDefinition.Kind.RECORD,
        )
        .select_related('definition')
        .prefetch_related('activations')
        .first()
    )
    if task is None:
        return None
    floor = organization.tasks_started_on or on_date
    if task.active_from and task.active_from > floor:
        floor = task.active_from
    if on_date < floor:
        return None
    for span in task.activations.all():
        if span.started_on <= on_date and (span.ended_on is None or on_date <= span.ended_on):
            return task
    return None


def _open_receipt(organization, user, receipt):
    _require_operate(user, organization)
    locked = _receipt_for(organization, receipt)
    if locked.status != GoodsReceipt.Status.OPEN:
        raise ValidationError('Zaključan prijem se ne menja.')
    return locked


def _line_for(organization, user, line):
    _require_operate(user, organization)
    line_id = line.pk if hasattr(line, 'pk') else line
    try:
        return (
            GoodsReceiptLine.objects
            .select_related('goods_receipt')
            .get(pk=line_id, goods_receipt__organization=organization)
        )
    except GoodsReceiptLine.DoesNotExist as exc:
        raise GoodsReceiptLine.DoesNotExist('Stavka nije dostupna.') from exc


def _receipt_for(organization, receipt):
    receipt_id = receipt.pk if hasattr(receipt, 'pk') else receipt
    try:
        return (
            GoodsReceipt.objects
            .select_related('task_occurrence', 'organization')
            .prefetch_related('lines')
            .get(pk=receipt_id, organization=organization)
        )
    except GoodsReceipt.DoesNotExist as exc:
        raise GoodsReceipt.DoesNotExist('Prijem nije dostupan.') from exc


def _lock_receipt(receipt_id, organization):
    qs = GoodsReceipt.objects.filter(pk=receipt_id, organization=organization)
    if connection.features.has_select_for_update:
        qs = qs.select_for_update()
    try:
        return qs.prefetch_related('lines').select_related('task_occurrence').get()
    except GoodsReceipt.DoesNotExist as exc:
        raise GoodsReceipt.DoesNotExist('Prijem nije dostupan.') from exc


def _lock_occurrence(occurrence_id, organization):
    qs = TaskOccurrence.objects.filter(pk=occurrence_id, organization=organization)
    if connection.features.has_select_for_update:
        qs = qs.select_for_update()
    return qs.get()


def _validated_line_fields(fields, *, require_complete):
    unknown = set(fields) - set(LINE_FIELDS)
    if unknown:
        raise ValidationError(f'Nepoznata polja stavke: {", ".join(sorted(unknown))}.')

    raw_material = (fields.get('raw_material') or '').strip()
    manufacturer = (fields.get('manufacturer') or '').strip()
    quantity = (fields.get('quantity') or '').strip()
    visual_check = fields.get('visual_check') or ''
    product_safety = fields.get('product_safety') or ''
    note = (fields.get('note') or '').strip()
    errors = {}
    if require_complete and not raw_material:
        errors['raw_material'] = 'Upiši sirovinu.'
    if require_complete and not manufacturer:
        errors['manufacturer'] = 'Upiši proizvođača.'
    if require_complete and not quantity:
        errors['quantity'] = 'Upiši količinu.'
    if require_complete and visual_check not in GoodsReceiptLine.Check.values:
        errors['visual_check'] = 'Izaberi vizuelnu kontrolu.'
    if require_complete and product_safety not in GoodsReceiptLine.Check.values:
        errors['product_safety'] = 'Izaberi bezbednost proizvoda.'
    if errors:
        raise ValidationError(errors)

    data = {
        'raw_material': raw_material,
        'manufacturer': manufacturer,
        'quantity': quantity,
        'visual_check': visual_check,
        'product_safety': product_safety,
        'note': note,
    }
    if 'sort_order' in fields:
        data['sort_order'] = fields['sort_order']
    return data
