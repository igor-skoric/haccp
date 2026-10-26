from accounts.models import User

from .models import Organization


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            if user.organization_id:
                request.tenant = user.organization
            elif self._can_pick_org(user):
                request.tenant = self._selected_org(request)
        return self.get_response(request)

    def _can_pick_org(self, user):
        return user.is_superuser or user.role == User.Role.PLATFORM_ADMIN

    def _selected_org(self, request):
        explicit = self._org_from_request(request)
        if explicit is not None:
            request.session['platform_org_id'] = explicit.pk
            return explicit
        org_id = request.session.get('platform_org_id')
        if not org_id:
            return None
        return Organization.objects.filter(pk=org_id).first()

    def _org_from_request(self, request):
        raw = request.GET.get('objekat')
        if raw is None or not str(raw).isdigit():
            return None
        return Organization.objects.filter(pk=int(raw)).first()
