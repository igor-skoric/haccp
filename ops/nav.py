"""Bezbedan kontekst povratka za evidencije OB-11 / OB-15."""

from django.urls import reverse

BACK_CHOICES = frozenset({
    'today',
    'tasks',
    'hygiene_list',
    'receiving_list',
    'receiving_open',
})


def parse_back(request, default='today'):
    raw = request.POST.get('from') or request.GET.get('from') or default
    if raw in BACK_CHOICES:
        return raw
    return default if default in BACK_CHOICES else 'today'


def back_url(from_key, default='today'):
    key = from_key if from_key in BACK_CHOICES else default
    return reverse(key)


def with_from(url, from_key):
    if not from_key or from_key not in BACK_CHOICES:
        return url
    sep = '&' if '?' in url else '?'
    return f'{url}{sep}from={from_key}'
