from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.permissions import is_platform_admin
from documents.views import library_counts


def home(request):
    if request.user.is_authenticated:
        if (
            getattr(request, 'impersonator', None) is None
            and request.user.organization_id is None
            and is_platform_admin(request.user)
        ):
            return redirect('platform_clients')
        return redirect('today')
    return redirect('login')


@login_required
def dashboard(request):
    tenant = request.tenant
    industry = tenant.industry if tenant else None
    return render(request, 'core/dashboard.html', {
        'industry': industry,
        'cards': library_counts(),
        'nav': 'settings',
        'back_url': reverse('settings'),
    })
