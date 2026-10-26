from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import can_configure, require_tenant
from organizations.models import OrganizationSettings

from .forms import (
    CorrectiveActionForm,
    GoodsReceiptLineForm,
    ReceivingCancelForm,
    ReceivingVerifyForm,
    TemperatureReadingForm,
)
from .hygiene import seed_lines, split_lines
from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    HygieneCheck,
    HygieneLine,
    TaskDefinition,
    TaskOccurrence,
    TemperatureReading,
)
from .receiving import (
    active_receiving_task,
    add_goods_receipt_line,
    cancel_goods_receipt,
    complete_goods_receipt,
    create_goods_receipt,
    delete_goods_receipt_line,
    update_goods_receipt_line,
    verify_goods_receipt,
)
from .nav import back_url, parse_back, with_from
from .task_board import close_hygiene_task, complete_task, load_task_board, sync_hygiene_reopen
from .temperatures import (
    add_corrective_action,
    ensure_cold_spots,
    measured_today_count,
    open_alerts,
    recent_history,
    record_temperature,
    sensor_cards,
)


def _org(request):
    return getattr(request, 'tenant', None)


def _alarm_kwargs(org):
    if org is None:
        return {}
    try:
        cfg = org.settings
    except OrganizationSettings.DoesNotExist:
        return {}
    return {
        'min_c': float(cfg.temp_min_c),
        'max_c': float(cfg.temp_max_c),
        'stale_minutes': cfg.sensor_stale_minutes,
        'alarms_enabled': cfg.alarms_enabled,
    }


def _hygiene_for_today(org):
    if not org:
        return None
    return HygieneCheck.objects.filter(
        organization=org,
        work_date=timezone.localdate(),
    ).prefetch_related('lines').first()


@require_tenant
def today(request):
    org = _org(request)
    ensure_cold_spots(org)
    sensors = sensor_cards(org)
    alerts = [a for a in open_alerts(org) if a['open']]
    board = load_task_board(org, from_key='today')
    measured, total = measured_today_count(org)
    counts = board['counts']
    return render(request, 'ops/today.html', {
        'nav': 'today',
        'sensors': sensors,
        'alerts': alerts,
        'for_today': board['for_today'],
        'hygiene_continue': board['hygiene_continue'],
        'receiving': board['receiving'],
        'backlog_preview': board['backlog_preview'],
        'backlog_more': board['backlog_more'],
        'todo_count': counts['todo'],
        'in_progress_count': counts['in_progress'],
        'open_receipts_count': counts['open_receipts'],
        'missed_count': counts['missed'],
        'alert_count': len(alerts),
        'ok_count': sum(1 for s in sensors if s['status'] == 'ok'),
        'measured_today': measured,
        'spots_total': total,
        'hygiene_today': _hygiene_for_today(org),
        'from_key': 'today',
    })


@require_tenant
def temperatures(request):
    org = _org(request)
    ensure_cold_spots(org)
    limits = _alarm_kwargs(org)
    max_c = limits.get('max_c', 8.0)
    min_c = limits.get('min_c', 2.0)
    form = TemperatureReadingForm(organization=org)

    if request.method == 'POST':
        form = TemperatureReadingForm(request.POST, organization=org)
        if form.is_valid():
            try:
                record_temperature(
                    org,
                    request.user,
                    form.cleaned_data['cold_spot'],
                    form.cleaned_data['value_c'],
                    corrective_action=form.cleaned_data.get('corrective_action') or '',
                )
                messages.success(request, 'Merenje je sačuvano.')
                return redirect('temperatures')
            except PermissionDenied:
                return HttpResponseForbidden()
            except ValidationError as exc:
                for text in _validation_messages(exc):
                    messages.error(request, text)

    sensors = sensor_cards(org)
    history = recent_history(org)
    measured, total = measured_today_count(org)
    return render(request, 'ops/temperatures.html', {
        'nav': 'temps',
        'sensors': sensors,
        'history': history,
        'history_label': 'Poslednja merenja',
        'max_c': max_c,
        'min_c': min_c,
        'form': form,
        'measured_today': measured,
        'spots_total': total,
    })


@require_tenant
@require_POST
def temperature_corrective(request, pk):
    org = _org(request)
    reading = get_object_or_404(
        TemperatureReading.objects.select_related('cold_spot'),
        pk=pk,
        organization=org,
    )
    form = CorrectiveActionForm(request.POST)
    if form.is_valid():
        try:
            add_corrective_action(
                org,
                request.user,
                reading,
                form.cleaned_data['corrective_action'],
            )
            messages.success(request, 'Korektivna mera je upisana.')
        except PermissionDenied:
            return HttpResponseForbidden()
        except ValidationError as exc:
            for text in _validation_messages(exc):
                messages.error(request, text)
    else:
        messages.error(request, 'Upiši korektivnu meru.')
    next_name = request.POST.get('next')
    if next_name == 'temperatures':
        return redirect('temperatures')
    return redirect('alerts')


@require_tenant
def tasks_page(request):
    org = _org(request)
    board = load_task_board(org, from_key='tasks')
    return render(request, 'ops/tasks.html', {
        'nav': 'tasks',
        'for_today': board['for_today'],
        'hygiene_continue': board['hygiene_continue'],
        'receiving': board['receiving'],
        'completed_tasks': board['completed'],
        'missed_tasks': board['missed'],
        'receiving_available': board['receiving_available'],
        'from_key': 'tasks',
    })


@require_tenant
@require_POST
def task_done(request, pk):
    org = _org(request)
    occurrence = get_object_or_404(
        TaskOccurrence.objects.select_related('organization_task__definition'),
        pk=pk,
        organization=org,
    )
    next_name = request.POST.get('next')
    if next_name not in {'today', 'tasks'}:
        next_name = 'today'
    if occurrence.organization_task.definition.kind != TaskDefinition.Kind.CONFIRM:
        return HttpResponseForbidden()
    if occurrence.status == TaskOccurrence.Status.OPEN:
        complete_task(occurrence, request.user, timezone.now())
    return redirect(next_name)


@require_tenant
def alerts(request):
    org = _org(request)
    ensure_cold_spots(org)
    rows = open_alerts(org)
    return render(request, 'ops/alerts.html', {
        'nav': 'alerts',
        'alerts': rows,
        'open_count': sum(1 for a in rows if a['open']),
        'corrective_form': CorrectiveActionForm(),
    })


def _redirect_detail(view_name, pk, from_key):
    return redirect(with_from(reverse(view_name, args=[pk]), from_key))


@require_tenant
def hygiene_list(request):
    org = _org(request)
    checks = []
    if org:
        checks = (
            HygieneCheck.objects
            .filter(organization=org)
            .prefetch_related('lines')[:40]
        )
    return render(request, 'ops/hygiene_list.html', {
        'nav': 'tasks',
        'checks': checks,
        'hygiene_today': _hygiene_for_today(org),
        'back_url': reverse('tasks'),
        'from_key': 'hygiene_list',
    })


@require_tenant
def hygiene_open_today(request):
    org = _org(request)
    from_key = parse_back(request, default='today')
    if not org:
        messages.error(request, 'Nalog nije vezan za objekat.')
        return redirect(back_url(from_key))

    work_date = timezone.localdate()
    check = HygieneCheck.objects.filter(
        organization=org,
        work_date=work_date,
    ).first()
    if not check:
        check = HygieneCheck.objects.create(
            organization=org,
            work_date=work_date,
            created_by=request.user,
        )
        seed_lines(check)
        messages.success(request, 'Kreirana je današnja ček lista higijene (OB-11).')
    return _redirect_detail('hygiene_detail', check.pk, from_key)


@require_tenant
def hygiene_detail(request, pk):
    org = _org(request)
    from_key = parse_back(request, default='hygiene_list')
    check = get_object_or_404(
        HygieneCheck.objects.prefetch_related('lines'),
        pk=pk,
        organization=org,
    )

    if request.method == 'POST':
        from_key = parse_back(request, default=from_key)
        with transaction.atomic():
            action = request.POST.get('action', 'save')
            if check.status == HygieneCheck.Status.DONE and action != 'reopen':
                messages.info(request, 'Zapis je završen. Možeš ga samo pregledati ili ponovo otvoriti.')
                return _redirect_detail('hygiene_detail', check.pk, from_key)

            if action == 'reopen' and check.status == HygieneCheck.Status.DONE:
                check.status = HygieneCheck.Status.OPEN
                check.completed_by = None
                check.completed_at = None
                check.save(update_fields=['status', 'completed_by', 'completed_at', 'updated_at'])
                sync_hygiene_reopen(check)
                messages.success(request, 'Ček lista je ponovo otvorena.')
                return _redirect_detail('hygiene_detail', check.pk, from_key)

            check.note = (request.POST.get('note') or '').strip()
            now = timezone.now()
            for line in check.lines.all():
                marked = request.POST.get(f'line_{line.pk}') == 'on'
                if marked != line.is_done:
                    line.is_done = marked
                    line.done_at = now if marked else None
                    line.done_by = request.user if marked else None
                    line.save(update_fields=['is_done', 'done_at', 'done_by'])

            check.save(update_fields=['note', 'updated_at'])

            if action == 'complete':
                if not check.required_done:
                    messages.error(
                        request,
                        'Za završetak označi sve svakodnevne (SP) stavke.',
                    )
                    return _redirect_detail('hygiene_detail', check.pk, from_key)
                check.status = HygieneCheck.Status.DONE
                check.completed_by = request.user
                check.completed_at = now
                check.save(update_fields=[
                    'status', 'completed_by', 'completed_at', 'updated_at',
                ])
                close_hygiene_task(check, request.user, now)
                messages.success(request, 'Higijena za danas je sačuvana i završena.')
                return _redirect_detail('hygiene_detail', check.pk, from_key)

            messages.success(request, 'Izmene su sačuvane.')
            return _redirect_detail('hygiene_detail', check.pk, from_key)

    daily_lines, periodic_lines = split_lines(check)
    return render(request, 'ops/hygiene_detail.html', {
        'nav': 'tasks',
        'check': check,
        'daily_lines': daily_lines,
        'periodic_lines': periodic_lines,
        'readonly': check.status == HygieneCheck.Status.DONE,
        'back_url': back_url(from_key, default='hygiene_list'),
        'from_key': from_key,
        'history_url': reverse('hygiene_list'),
    })


@require_tenant
@require_POST
def hygiene_toggle(request, pk, line_id):
    """Brzi toggle jedne stavke (opciono za kasnije AJAX)."""
    org = _org(request)
    check = get_object_or_404(HygieneCheck, pk=pk, organization=org)
    if check.status == HygieneCheck.Status.DONE:
        return redirect('hygiene_detail', pk=check.pk)
    line = get_object_or_404(HygieneLine, pk=line_id, record=check)
    line.is_done = not line.is_done
    line.done_at = timezone.now() if line.is_done else None
    line.done_by = request.user if line.is_done else None
    line.save(update_fields=['is_done', 'done_at', 'done_by'])
    return redirect('hygiene_detail', pk=check.pk)


def _validation_messages(exc):
    if hasattr(exc, 'messages'):
        return [str(item) for item in exc.messages]
    return [str(exc)]


def _line_form(data=None, *, line=None, prefix=None):
    initial = None
    if line is not None:
        initial = {
            'raw_material': line.raw_material,
            'manufacturer': line.manufacturer,
            'quantity': line.quantity,
            'visual_check': line.visual_check,
            'product_safety': line.product_safety,
            'note': line.note,
        }
    return GoodsReceiptLineForm(data, initial=initial, prefix=prefix)


@require_tenant
@require_POST
def receiving_create(request):
    org = _org(request)
    from_key = parse_back(request, default='today')
    try:
        receipt = create_goods_receipt(org, request.user)
    except PermissionDenied:
        return HttpResponseForbidden()
    except ValidationError as exc:
        for text in _validation_messages(exc):
            messages.error(request, text)
        next_name = request.POST.get('next')
        if next_name == 'list':
            return redirect('receiving_list')
        if next_name == 'tasks':
            return redirect('tasks')
        return redirect(back_url(from_key))
    messages.success(request, 'Otvoren je novi prijem sirovina (OB-15).')
    return _redirect_detail('receiving_detail', receipt.pk, from_key)


@require_tenant
def receiving_list(request):
    org = _org(request)
    receipts = []
    if org:
        rows = (
            GoodsReceipt.objects
            .filter(organization=org)
            .select_related('created_by', 'completed_by', 'cancelled_by')
            .annotate(line_count=Count('lines'))
            .order_by('-received_on', '-id')[:40]
        )
        for item in rows:
            item.result = item.control_result() if item.status == GoodsReceipt.Status.DONE else None
            receipts.append(item)
    return render(request, 'ops/receiving_list.html', {
        'nav': 'tasks',
        'receipts': receipts,
        'receiving_available': active_receiving_task(org) is not None if org else False,
        'back_url': reverse('tasks'),
        'from_key': 'receiving_list',
    })


@require_tenant
def receiving_open(request):
    org = _org(request)
    return_key = parse_back(request, default='today')
    board = load_task_board(org, from_key='receiving_open')
    return render(request, 'ops/receiving_open.html', {
        'nav': 'tasks' if return_key == 'tasks' else 'today',
        'open_receipts': board['open_receipts'],
        'receiving_available': board['receiving_available'],
        'back_url': back_url(return_key, default='today'),
        'from_key': 'receiving_open',
        'return_key': return_key,
    })


@require_tenant
def receiving_detail(request, pk):
    org = _org(request)
    from_key = parse_back(request, default='receiving_list')
    receipt = get_object_or_404(
        GoodsReceipt.objects.select_related(
            'organization',
            'created_by',
            'completed_by',
            'cancelled_by',
            'verified_by',
            'task_occurrence',
        ).prefetch_related('lines'),
        pk=pk,
        organization=org,
    )
    readonly = receipt.status != GoodsReceipt.Status.OPEN
    line_form = _line_form()
    line_forms = {}
    verify_form = ReceivingVerifyForm()
    cancel_form = ReceivingCancelForm()

    if request.method == 'POST':
        from_key = parse_back(request, default=from_key)
        action = request.POST.get('action')
        if receipt.status == GoodsReceipt.Status.CANCELLED:
            messages.info(request, 'Prijem je otkazan. Možeš ga samo pregledati.')
            return _redirect_detail('receiving_detail', receipt.pk, from_key)
        if (
            receipt.status == GoodsReceipt.Status.DONE
            and action not in {'complete', 'verify'}
        ):
            messages.info(request, 'Prijem je završen. Možeš ga samo pregledati.')
            return _redirect_detail('receiving_detail', receipt.pk, from_key)

        try:
            if action == 'add_line':
                line_form = _line_form(request.POST)
                if line_form.is_valid():
                    add_goods_receipt_line(org, request.user, receipt, **line_form.cleaned_data)
                    messages.success(request, 'Stavka je dodata.')
                    return _redirect_detail('receiving_detail', receipt.pk, from_key)
            elif action == 'update_line':
                line = get_object_or_404(
                    GoodsReceiptLine,
                    pk=request.POST.get('line_id'),
                    goods_receipt=receipt,
                )
                prefix = f'l{line.pk}'
                form = _line_form(request.POST, line=line, prefix=prefix)
                if form.is_valid():
                    update_goods_receipt_line(org, request.user, line, **form.cleaned_data)
                    messages.success(request, 'Stavka je sačuvana.')
                    return _redirect_detail('receiving_detail', receipt.pk, from_key)
                line_forms[line.pk] = form
            elif action == 'delete_line':
                line = get_object_or_404(
                    GoodsReceiptLine,
                    pk=request.POST.get('line_id'),
                    goods_receipt=receipt,
                )
                delete_goods_receipt_line(org, request.user, line)
                messages.success(request, 'Stavka je obrisana.')
                return _redirect_detail('receiving_detail', receipt.pk, from_key)
            elif action == 'complete':
                complete_goods_receipt(org, request.user, receipt)
                messages.success(request, 'Prijem je završen.')
                return _redirect_detail('receiving_detail', receipt.pk, from_key)
            elif action == 'cancel':
                cancel_form = ReceivingCancelForm(request.POST)
                if cancel_form.is_valid():
                    cancel_goods_receipt(
                        org,
                        request.user,
                        receipt,
                        reason=cancel_form.cleaned_data.get('cancellation_reason') or '',
                    )
                    messages.success(request, 'Prijem je otkazan.')
                    return _redirect_detail('receiving_detail', receipt.pk, from_key)
            elif action == 'verify':
                verify_form = ReceivingVerifyForm(request.POST)
                if verify_form.is_valid():
                    verify_goods_receipt(
                        org,
                        request.user,
                        receipt,
                        verifier_role=verify_form.cleaned_data['verifier_role'],
                    )
                    messages.success(request, 'Prijem je verifikovan.')
                    return _redirect_detail('receiving_detail', receipt.pk, from_key)
            else:
                return HttpResponseNotAllowed(['POST'])
        except PermissionDenied:
            return HttpResponseForbidden()
        except ValidationError as exc:
            for text in _validation_messages(exc):
                messages.error(request, text)
            return _redirect_detail('receiving_detail', receipt.pk, from_key)

    lines = []
    for item in receipt.lines.all():
        form = line_forms.get(item.pk) or _line_form(line=item, prefix=f'l{item.pk}')
        item.form = form
        lines.append(item)

    receipt.refresh_from_db()
    can_verify = (
        receipt.status == GoodsReceipt.Status.DONE
        and not receipt._verification_complete()
        and can_configure(request.user, org)
        and receipt.completed_by_id != request.user.pk
    )
    return render(request, 'ops/receiving_detail.html', {
        'nav': 'tasks',
        'receipt': receipt,
        'lines': lines,
        'line_form': line_form,
        'readonly': receipt.status != GoodsReceipt.Status.OPEN,
        'control_result': receipt.control_result() if receipt.status == GoodsReceipt.Status.DONE else None,
        'can_verify': can_verify,
        'verify_form': verify_form,
        'cancel_form': cancel_form,
        'can_cancel': receipt.status == GoodsReceipt.Status.OPEN,
        'back_url': back_url(from_key, default='receiving_list'),
        'from_key': from_key,
        'history_url': reverse('receiving_list'),
    })
