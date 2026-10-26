from django.db import migrations


def seed_and_migrate(apps, schema_editor):
    from ops.task_catalog import migrate_day_tasks, seed_task_catalog

    seed_task_catalog(apps)
    migrate_day_tasks(apps)


def remove_seed(apps, schema_editor):
    TaskOccurrence = apps.get_model('ops', 'TaskOccurrence')
    OrganizationTask = apps.get_model('ops', 'OrganizationTask')
    TaskDefinition = apps.get_model('ops', 'TaskDefinition')
    TaskOccurrence.objects.all().delete()
    OrganizationTask.objects.all().delete()
    TaskDefinition.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0003_task_definitions'),
        ('documents', '0003_inspection_catalog'),
    ]

    operations = [
        migrations.RunPython(seed_and_migrate, remove_seed),
    ]
