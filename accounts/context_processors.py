from accounts.permissions import (
    can_configure,
    can_manage_members,
    can_operate,
    is_platform_admin,
)


def access(request):
    user = getattr(request, 'user', None)
    tenant = getattr(request, 'tenant', None)
    impersonator = getattr(request, 'impersonator', None)
    is_impersonating = impersonator is not None
    if user is None or not user.is_authenticated:
        return {
            'can_operate': False,
            'can_configure': False,
            'can_manage_members': False,
            'can_pick_org': False,
            'impersonator': None,
            'is_impersonating': False,
        }
    return {
        'can_operate': can_operate(user, tenant),
        'can_configure': can_configure(user, tenant),
        'can_manage_members': can_manage_members(user, tenant),
        'can_pick_org': (
            not is_impersonating
            and user.organization_id is None
            and is_platform_admin(user)
        ),
        'impersonator': impersonator,
        'is_impersonating': is_impersonating,
    }
