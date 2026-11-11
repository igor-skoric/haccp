from django.db import migrations


def seed_universal_fines(apps, schema_editor):
    from documents.build_inspection import build_entries

    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    entry = next(item for item in build_entries() if item['code'] == 'IN-01')
    DocumentTemplate.objects.update_or_create(
        code=entry['code'],
        defaults={
            'kind': entry['kind'],
            'title': entry['title'],
            'source_filename': entry['source_filename'],
            'body': entry['body'],
            'is_fixed': entry['is_fixed'],
            'note': entry['note'],
            'sort_order': entry['sort_order'],
            'checklist': entry['checklist'],
        },
    )


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0005_inspection_runs'),
    ]

    operations = [
        migrations.RunPython(seed_universal_fines, noop_reverse),
    ]
