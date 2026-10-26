from django.db import migrations, models
from django.utils import timezone


def anchor_organizations(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    Organization.objects.filter(tasks_started_on__isnull=True).update(
        tasks_started_on=timezone.localdate(),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0003_organizationsettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='tasks_started_on',
            field=models.DateField(
                help_text='Dan od kog objekat koristi zadatke. Raniji periodi se ne prave.',
                null=True,
                verbose_name='zadaci važe od',
            ),
        ),
        migrations.RunPython(anchor_organizations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='organization',
            name='tasks_started_on',
            field=models.DateField(
                help_text='Dan od kog objekat koristi zadatke. Raniji periodi se ne prave.',
                verbose_name='zadaci važe od',
            ),
        ),
    ]
