import copy

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.permissions import can_operate

from .checklist import (
    annotate_progress,
    clean_answers,
    clean_notes,
    is_checklist,
    is_complete,
    present_run,
    progress_counts,
)
from .formatting import format_fixed_document
from .kinds import KIND_BY_CODE, KINDS
from .models import DocumentTemplate, InspectionRecord


@login_required
def library(request, kind):
    meta = KIND_BY_CODE[kind]
    documents = list(
        DocumentTemplate.objects.filter(kind=kind).order_by('-is_fixed', 'sort_order')
    )
    annotate_progress(documents, getattr(request, 'tenant', None))
    return render(request, 'documents/list.html', {
        'meta': meta,
        'documents': documents,
        'nav': 'docs',
        'back_url': reverse('dashboard'),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def detail(request, code):
    document = get_object_or_404(DocumentTemplate, code=code)
    if is_checklist(document):
        return _checklist_index(request, document)
    meta = KIND_BY_CODE[document.kind]
    view = {'mode': 'empty', 'blocks': []}
    if document.is_fixed and document.body:
        view = format_fixed_document(
            document.code,
            document.body,
            kind=document.kind,
        )
    return render(request, 'documents/detail.html', {
        'document': document,
        'meta': meta,
        'nav': 'docs',
        'back_url': reverse(meta['url_name']),
        'view': view,
    })


def _checklist_index(request, document):
    meta = KIND_BY_CODE[document.kind]
    tenant = getattr(request, 'tenant', None)
    writable = can_operate(request.user, tenant)
    if request.method == 'POST':
        if not writable or request.POST.get('action') != 'start':
            return render(request, '403.html', status=403)
        record = InspectionRecord.objects.create(
            organization=tenant,
            template=document,
            snapshot=copy.deepcopy(document.checklist),
            created_by=request.user,
            updated_by=request.user,
            status=InspectionRecord.Status.OPEN,
        )
        return redirect('inspection_run', code=document.code, pk=record.pk)
    runs = []
    if tenant is not None:
        runs = list(
            InspectionRecord.objects.filter(organization=tenant, template=document)
            .select_related('created_by', 'completed_by')
        )
        for run in runs:
            run.progress_done, run.progress_total = progress_counts(
                run.snapshot or document.checklist,
                run.answers,
            )
    return render(request, 'documents/detail.html', {
        'document': document,
        'meta': meta,
        'nav': 'docs',
        'back_url': reverse(meta['url_name']),
        'runs': runs,
        'writable': writable,
        'view': {
            'mode': 'checklist_index',
            'subject': tenant.name if tenant else '',
        },
    })


@login_required
@require_http_methods(['GET', 'POST'])
def inspection_run(request, code, pk):
    document = get_object_or_404(DocumentTemplate, code=code)
    if not is_checklist(document):
        raise Http404
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        raise Http404
    if request.method == 'POST':
        return _save_run(request, document, pk, tenant)
    record = get_object_or_404(
        InspectionRecord.objects.select_related('created_by', 'completed_by'),
        pk=pk,
        template=document,
        organization=tenant,
    )
    return _render_run(request, document, record, tenant)


def _save_run(request, document, pk, tenant):
    if not can_operate(request.user, tenant):
        return render(request, '403.html', status=403)
    with transaction.atomic():
        queryset = InspectionRecord.objects.filter(
            pk=pk,
            template=document,
            organization=tenant,
        )
        if connection.features.has_select_for_update:
            queryset = queryset.select_for_update()
        record = queryset.first()
        if record is None:
            raise Http404
        if record.status != InspectionRecord.Status.OPEN:
            return render(request, '403.html', status=403)
        checklist = record.snapshot or document.checklist
        answers = clean_answers(checklist, request.POST)
        notes = clean_notes(checklist, request.POST)
        remarks = (request.POST.get('remarks') or '').strip()
        record.answers = answers
        record.notes = notes
        record.remarks = remarks
        record.updated_by = request.user
        if request.POST.get('action') == 'complete':
            if not is_complete(checklist, answers):
                record.save(update_fields=[
                    'answers', 'notes', 'remarks', 'updated_at', 'updated_by',
                ])
                messages.error(
                    request,
                    'Kontrola može da se završi tek kada su sva pitanja odgovorena.',
                )
                return redirect('inspection_run', code=document.code, pk=record.pk)
            record.status = InspectionRecord.Status.DONE
            record.completed_by = request.user
            record.completed_at = timezone.now()
            record.save(update_fields=[
                'answers', 'notes', 'remarks', 'status',
                'completed_by', 'completed_at', 'updated_at', 'updated_by',
            ])
            messages.success(request, 'Kontrola je završena.')
            return redirect('document', code=document.code)
        record.save(update_fields=[
            'answers', 'notes', 'remarks', 'updated_at', 'updated_by',
        ])
    messages.success(request, 'Kontrola je sačuvana.')
    return redirect('document', code=document.code)


def _render_run(request, document, record, tenant):
    meta = KIND_BY_CODE[document.kind]
    writable = (
        can_operate(request.user, tenant)
        and record.status == InspectionRecord.Status.OPEN
    )
    return render(request, 'documents/inspection_run.html', {
        'document': document,
        'run': record,
        'meta': meta,
        'nav': 'docs',
        'back_url': reverse('document', args=[document.code]),
        'view': present_run(document, record, tenant=tenant, writable=writable),
    })


def library_counts():
    rows = (
        DocumentTemplate.objects.values('kind')
        .annotate(
            total=Count('id'),
            fixed=Count('id', filter=Q(is_fixed=True)),
        )
    )
    by_kind = {row['kind']: row for row in rows}
    cards = []
    for item in KINDS:
        stats = by_kind.get(item['code'], {'total': 0, 'fixed': 0})
        cards.append({**item, **stats})
    return cards
