from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    # Živi moduli: kompleksna aktivacija i katalog.
    from ops.hygiene_periodic import (
        activate_periodic_hygiene_for_organization,
        ensure_periodic_hygiene_definitions,
    )
    from organizations.models import Organization

    ensure_periodic_hygiene_definitions()
    on_date = timezone.localdate()
    for organization in Organization.objects.order_by('pk'):
        activate_periodic_hygiene_for_organization(organization, on_date=on_date)


def backwards(apps, schema_editor):
    TaskDefinition = apps.get_model('ops', 'TaskDefinition')
    OrganizationTask = apps.get_model('ops', 'OrganizationTask')
    OrganizationTaskActivation = apps.get_model('ops', 'OrganizationTaskActivation')

    OrganizationTaskActivation.objects.filter(
        organization_task__definition__code__in=('t2w', 't2m'),
    ).delete()
    OrganizationTask.objects.filter(definition__code__in=('t2w', 't2m')).delete()
    TaskDefinition.objects.filter(code__in=('t2w', 't2m')).delete()
    # t4 se ne vraća automatski na enabled — ručni korak ako zatreba.


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0008_goods_receipt_cancel'),
        ('organizations', '0004_tasks_started_on'),
        ('documents', '0002_seed_catalog'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
