from accounts.impersonation import VIEW_AS_SESSION_KEY, can_view_as
from accounts.models import User
from accounts.permissions import is_platform_admin


class ImpersonationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and is_platform_admin(user):
            target_id = request.session.get(VIEW_AS_SESSION_KEY)
            if target_id:
                target = (
                    User.objects.filter(pk=target_id)
                    .select_related('organization')
                    .first()
                )
                if can_view_as(user, target):
                    request.impersonator = user
                    request.user = target
                else:
                    request.session.pop(VIEW_AS_SESSION_KEY, None)
        return self.get_response(request)
