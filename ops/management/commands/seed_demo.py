from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from ops.scheduling import assign_organization_tasks
from ops.temperatures import ensure_cold_spots
from organizations.models import Industry, Organization, OrganizationSettings

DEMO_PASSWORD = 'demo1234'
ADMIN_PASSWORD = 'admin'


class Command(BaseCommand):
    help = (
        'Priprema demo klijente i naloge za lokalno testiranje. '
        f'Lozinka za demo naloge: {DEMO_PASSWORD}; admin: {ADMIN_PASSWORD}'
    )

    def handle(self, *args, **options):
        with transaction.atomic():
            bakery = self._org('Pekara Proba', 'proizvodnja')
            sweet = self._org('Slatkoca', 'poslasticarnica')
            cafe = self._org('Kafic Demo', 'kafic')

            owner = self._user(
                'marko.proba',
                bakery,
                User.Role.OWNER,
                first_name='Marko',
                last_name='Proba',
            )
            self._user(
                'ana.radnik',
                bakery,
                User.Role.STAFF,
                first_name='Ana',
                last_name='Radnik',
            )
            self._user(
                'igorskoric',
                sweet,
                User.Role.OWNER,
                first_name='Igor',
                last_name='Skoric',
            )
            self._user(
                'admin',
                None,
                User.Role.PLATFORM_ADMIN,
                is_staff=True,
                is_superuser=True,
                password=ADMIN_PASSWORD,
            )

            for org in (bakery, sweet, cafe):
                OrganizationSettings.objects.get_or_create(organization=org)
                assign_organization_tasks(org)
                ensure_cold_spots(org)

        self.stdout.write(self.style.SUCCESS('Demo podaci su spremni.'))
        self.stdout.write(f'  marko.proba / {DEMO_PASSWORD}  (owner · {bakery.name})')
        self.stdout.write(f'  ana.radnik / {DEMO_PASSWORD}   (staff · {bakery.name})')
        self.stdout.write(f'  igorskoric / {DEMO_PASSWORD}   (owner · {sweet.name})')
        self.stdout.write(f'  admin / {ADMIN_PASSWORD}             (platform admin)')
        self.stdout.write(f'  vlasnik pekare: {owner.username}')

    def _org(self, name, industry_code):
        industry = Industry.objects.filter(code=industry_code).first()
        if industry is None:
            industry = Industry.objects.order_by('sort_order', 'pk').first()
        org, _created = Organization.objects.get_or_create(
            name=name,
            defaults={'industry': industry},
        )
        if org.industry_id != industry.pk:
            org.industry = industry
            org.save(update_fields=['industry'])
        return org

    def _user(self, username, organization, role, **extra):
        user = User.objects.filter(username=username).first()
        if user is None:
            user = User(username=username)
        user.organization = organization
        user.role = role
        user.is_staff = extra.get('is_staff', False)
        user.is_superuser = extra.get('is_superuser', False)
        user.first_name = extra.get('first_name', user.first_name)
        user.last_name = extra.get('last_name', user.last_name)
        user.is_active = True
        user.set_password(extra.get('password', DEMO_PASSWORD))
        user.save()
        return user
