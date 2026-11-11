import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def preserve_existing_runs(apps, schema_editor):
    InspectionRecord = apps.get_model('documents', 'InspectionRecord')
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    templates = {
        row.pk: row.checklist or {}
        for row in DocumentTemplate.objects.all()
    }
    for record in InspectionRecord.objects.all().iterator():
        InspectionRecord.objects.filter(pk=record.pk).update(
            snapshot=record.snapshot or templates.get(record.template_id, {}),
            created_at=record.updated_at,
            created_by_id=record.updated_by_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0004_inspection_checklists'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='inspectionrecord',
            name='status',
            field=models.CharField(
                choices=[('open', 'U toku'), ('done', 'Završena')],
                default='open',
                max_length=8,
                verbose_name='status',
            ),
        ),
        migrations.AddField(
            model_name='inspectionrecord',
            name='notes',
            field=models.JSONField(blank=True, default=dict, verbose_name='napomene'),
        ),
        migrations.AddField(
            model_name='inspectionrecord',
            name='snapshot',
            field=models.JSONField(blank=True, default=dict, verbose_name='verzija liste'),
        ),
        migrations.AddField(
            model_name='inspectionrecord',
            name='created_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='započeto'),
        ),
        migrations.AddField(
            model_name='inspectionrecord',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='inspection_runs_started',
                to=settings.AUTH_USER_MODEL,
                verbose_name='započeo',
            ),
        ),
        migrations.AddField(
            model_name='inspectionrecord',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='završeno'),
        ),
        migrations.AddField(
            model_name='inspectionrecord',
            name='completed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='inspection_runs_completed',
                to=settings.AUTH_USER_MODEL,
                verbose_name='završio',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='inspectionrecord',
            name='unique_inspection_per_client',
        ),
        migrations.RunPython(preserve_existing_runs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='inspectionrecord',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, blank=True, verbose_name='započeto'),
        ),
        migrations.AlterModelOptions(
            name='inspectionrecord',
            options={
                'ordering': ['-created_at', '-id'],
                'verbose_name': 'kontrola',
                'verbose_name_plural': 'kontrole',
            },
        ),
    ]
