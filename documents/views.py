from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .formatting import format_fixed_document
from .kinds import KIND_BY_CODE, KINDS
from .models import DocumentTemplate


@login_required
def library(request, kind):
    meta = KIND_BY_CODE[kind]
    documents = DocumentTemplate.objects.filter(kind=kind).order_by('-is_fixed', 'sort_order')
    return render(request, 'documents/list.html', {
        'meta': meta,
        'documents': documents,
        'nav': 'settings',
        'back_url': reverse('dashboard'),
    })


@login_required
def detail(request, code):
    document = get_object_or_404(DocumentTemplate, code=code)
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
        'nav': 'settings',
        'back_url': reverse(meta['url_name']),
        'view': view,
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
