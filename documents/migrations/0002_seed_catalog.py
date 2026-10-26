import json
from pathlib import Path

from django.db import migrations


def load_catalog(apps, schema_editor):
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    path = Path(__file__).resolve().parents[1] / 'library' / 'catalog.json'
    rows = json.loads(path.read_text(encoding='utf-8'))
    for row in rows:
        code = row['code']
        DocumentTemplate.objects.update_or_create(
            code=code,
            defaults={
                'kind': row['kind'],
                'title': row['title'],
                'source_filename': row['source_filename'],
                'body': row['body'],
                'is_fixed': row['is_fixed'],
                'note': row['note'],
                'sort_order': row['sort_order'],
            },
        )


def clear_catalog(apps, schema_editor):
    apps.get_model('documents', 'DocumentTemplate').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('documents', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(load_catalog, clear_catalog),
    ]
