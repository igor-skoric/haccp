from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from accounts.impersonation import VIEW_AS_SESSION_KEY, can_view_as
from accounts.models import User
from accounts.permissions import is_platform_admin

from .forms import LoginForm, RegistrationForm


@method_decorator(ensure_csrf_cookie, name='dispatch')
@method_decorator(never_cache, name='dispatch')
class HaccpLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        user = self.request.user
        if user.organization_id is None and is_platform_admin(user):
            return reverse('platform_clients')
        return super().get_success_url()


class HaccpLogoutView(LogoutView):
    pass


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegistrationForm(request.POST or None, industry_code=request.GET.get('delatnost'))
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('dashboard')
    return render(request, 'accounts/register.html', {'form': form})


@login_required
@require_POST
def view_as_start(request, user_id):
    if getattr(request, 'impersonator', None) is not None:
        return HttpResponseForbidden()
    if not is_platform_admin(request.user):
        return HttpResponseForbidden()
    target = get_object_or_404(User, pk=user_id)
    if not can_view_as(request.user, target):
        return HttpResponseForbidden()
    request.session[VIEW_AS_SESSION_KEY] = target.pk
    return redirect('today')


@login_required
@require_POST
def view_as_stop(request):
    if getattr(request, 'impersonator', None) is None:
        return redirect('platform_clients')
    org_id = request.user.organization_id
    request.session.pop(VIEW_AS_SESSION_KEY, None)
    if org_id:
        return redirect('platform_client_detail', pk=org_id)
    return redirect('platform_clients')
