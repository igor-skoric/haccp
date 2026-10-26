from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import User
from accounts.permissions import can_configure, is_platform_admin, require_configure
from ops.models import OrganizationTask

from .forms import (
    AlarmsSettingsForm,
    OrganizationTaskSettingsForm,
    SensorSettingsForm,
    TemperatureSettingsForm,
)
from .models import Organization, OrganizationSettings


def _summary_alarms(cfg):
    return 'Uključeni' if cfg.alarms_enabled else 'Isključeni'


def _summary_temperature(cfg):
    return f'{cfg.temp_min_c}–{cfg.temp_max_c} °C'


def _summary_sensors(cfg):
    return f'{cfg.sensor_stale_minutes} min'


SECTIONS = (
    {
        'slug': 'alarmi',
        'title': 'Alarmi',
        'form': AlarmsSettingsForm,
        'summary': _summary_alarms,
    },
    {
        'slug': 'temperatura',
        'title': 'Temperatura',
        'form': TemperatureSettingsForm,
        'summary': _summary_temperature,
    },
    {
        'slug': 'senzori',
        'title': 'Senzori',
        'form': SensorSettingsForm,
        'summary': _summary_sensors,
    },
)
SECTION_BY_SLUG = {item['slug']: item for item in SECTIONS}


def _settings_target(request):
    if request.user.organization_id:
        return request.user.organization, None

    can_pick = (
        request.user.is_superuser
        or request.user.role == User.Role.PLATFORM_ADMIN
    )
    if not can_pick:
        return None, None

    organizations = list(Organization.objects.order_by('name'))
    return request.tenant, organizations


def _with_org(url, organizations, org):
    if organizations is not None and org is not None:
        return f'{url}?objekat={org.pk}'
    return url


def _task_summary(org):
    tasks = OrganizationTask.objects.filter(organization=org)
    total = tasks.count()
    if total == 0:
        return 'Nema dodeljenih'
    enabled = tasks.filter(enabled=True).count()
    return f'{enabled} od {total}'


def _activation_label(task):
    windows = list(task.activations.all())
    opened = next((item for item in windows if item.ended_on is None), None)
    if opened is not None and opened.started_on != task.active_from:
        return f'Trenutno uključenje od {opened.started_on:%d.%m.%Y.}'
    if opened is None and windows:
        last = max(windows, key=lambda item: (item.ended_on or item.started_on, item.pk))
        if last.ended_on is not None:
            return f'Isključeno {last.ended_on:%d.%m.%Y.}'
    return ''


def _task_meta(task):
    definition = task.definition
    parts = [definition.get_kind_display(), definition.get_cadence_display()]
    if definition.document_id:
        parts.append(definition.document.code)
    return ' · '.join(parts)


def _section_links(cfg, organizations, org):
    return [
        {
            'slug': item['slug'],
            'title': item['title'],
            'summary': item['summary'](cfg),
            'url': _with_org(
                reverse('settings_section', args=[item['slug']]),
                organizations,
                org,
            ),
        }
        for item in SECTIONS
    ]


def _require_platform_hub(request):
    if getattr(request, 'impersonator', None) is not None:
        return False
    return is_platform_admin(request.user)


@login_required
def platform_clients(request):
    if not _require_platform_hub(request):
        return HttpResponseForbidden()
    organizations = (
        Organization.objects.select_related('industry')
        .annotate(member_count=Count('members'))
        .order_by('name')
    )
    return render(request, 'organizations/platform_clients.html', {
        'nav': 'clients',
        'organizations': organizations,
    })


@login_required
def platform_client_detail(request, pk):
    if not _require_platform_hub(request):
        return HttpResponseForbidden()
    org = get_object_or_404(
        Organization.objects.select_related('industry'),
        pk=pk,
    )
    members = list(
        org.members.order_by('role', 'username')
    )
    return render(request, 'organizations/platform_client_detail.html', {
        'nav': 'clients',
        'organization': org,
        'members': members,
        'back_url': reverse('platform_clients'),
    })


@login_required
def settings_page(request):
    org, organizations = _settings_target(request)
    return render(request, 'organizations/settings.html', {
        'nav': 'settings',
        'config_url': _with_org(reverse('settings_config'), organizations, org),
    })


@login_required
def settings_config(request):
    org, organizations = _settings_target(request)
    picker_only = organizations is not None and org is None
    if not can_configure(request.user, org) and not picker_only:
        return HttpResponseForbidden()
    sections = []
    if org is not None:
        cfg, _created = OrganizationSettings.objects.get_or_create(organization=org)
        sections = _section_links(cfg, organizations, org)
        sections.append({
            'slug': 'zadaci',
            'title': 'Zadaci',
            'summary': _task_summary(org),
            'url': _with_org(reverse('task_settings'), organizations, org),
        })
    return render(request, 'organizations/settings_config.html', {
        'nav': 'settings',
        'organization': org,
        'organizations': organizations,
        'sections': sections,
        'back_url': _with_org(reverse('settings'), organizations, org),
    })


@require_configure
def settings_section(request, section):
    spec = SECTION_BY_SLUG.get(section)
    if spec is None:
        return redirect('settings')

    org, organizations = _settings_target(request)
    if org is None:
        return redirect('settings')

    cfg, _created = OrganizationSettings.objects.get_or_create(organization=org)
    back_url = _with_org(reverse('settings_config'), organizations, org)
    if request.method == 'POST':
        form = spec['form'](request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sačuvano.')
            return redirect(_with_org(
                reverse('settings_section', args=[section]),
                organizations,
                org,
            ))
    else:
        form = spec['form'](instance=cfg)

    return render(request, 'organizations/settings_section.html', {
        'nav': 'settings',
        'organization': org,
        'section': spec,
        'form': form,
        'back_url': back_url,
    })


@require_configure
def task_settings(request):
    org, organizations = _settings_target(request)
    if org is None or org.pk != request.tenant.pk:
        return HttpResponseForbidden()

    tasks = list(
        OrganizationTask.objects
        .filter(organization=request.tenant)
        .select_related('definition__document')
        .prefetch_related('activations')
    )
    bound = None
    if request.method == 'POST':
        raw = request.POST.get('task', '')
        if not str(raw).isdigit():
            raise Http404
        org_task = get_object_or_404(
            OrganizationTask.objects.select_related('definition__document'),
            pk=int(raw),
            organization=request.tenant,
        )
        bound = OrganizationTaskSettingsForm(
            request.POST,
            instance=org_task,
            prefix=f't{org_task.pk}',
        )
        if bound.is_valid():
            bound.save()
            messages.success(request, 'Sačuvano.')
            return redirect(_with_org(reverse('task_settings'), organizations, org))
        tasks = [
            bound.instance if task.pk == bound.instance.pk else task
            for task in tasks
        ]

    rows = []
    for task in tasks:
        form = bound if bound is not None and bound.instance.pk == task.pk else OrganizationTaskSettingsForm(
            instance=task,
            prefix=f't{task.pk}',
        )
        rows.append({
            'task': task,
            'form': form,
            'meta': _task_meta(task),
            'active_label': task.active_from.strftime('%d.%m.%Y.'),
            'current_label': _activation_label(task),
        })

    return render(request, 'organizations/task_settings.html', {
        'nav': 'settings',
        'organization': org,
        'rows': rows,
        'back_url': _with_org(reverse('settings_config'), organizations, org),
    })
