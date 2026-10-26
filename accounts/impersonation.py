VIEW_AS_SESSION_KEY = 'view_as_user_id'


def can_view_as(actor, target):
    from accounts.permissions import is_platform_admin

    if not is_platform_admin(actor):
        return False
    if target is None or not getattr(target, 'is_authenticated', True):
        return False
    if not target.organization_id:
        return False
    if is_platform_admin(target):
        return False
    return True
