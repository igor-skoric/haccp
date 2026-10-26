from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.models import User


def is_platform_admin(user):
    return bool(
        getattr(user, 'is_authenticated', False)
        and (user.is_superuser or user.role == User.Role.PLATFORM_ADMIN)
    )


def can_operate(user, tenant):
    if tenant is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.organization_id == tenant.pk and user.role in (User.Role.OWNER, User.Role.STAFF):
        return True
    if user.organization_id is None and is_platform_admin(user):
        return True
    return False


def can_configure(user, tenant):
    if tenant is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.organization_id == tenant.pk and user.role == User.Role.OWNER:
        return True
    if user.organization_id is None and is_platform_admin(user):
        return True
    return False


def can_manage_members(user, tenant):
    return can_configure(user, tenant)


def _forbid_unless(check):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            tenant = getattr(request, 'tenant', None)
            if not check(request.user, tenant):
                return render(request, '403.html', status=403)
            return view_func(request, *args, **kwargs)

        return login_required(_wrapped)

    return decorator


require_tenant = _forbid_unless(can_operate)
require_configure = _forbid_unless(can_configure)
