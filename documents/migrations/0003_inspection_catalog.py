from django.db import migrations


def seed_inspection(apps, schema_editor):
    from documents.build_inspection import build_entries

    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    for entry in build_entries():
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
            },
        )


def unseed_inspection(apps, schema_editor):
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    DocumentTemplate.objects.filter(code__in=['IN-01', 'IN-02', 'IN-03', 'IN-04']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('documents', '0002_seed_catalog'),
    ]

    operations = [
        migrations.RunPython(seed_inspection, unseed_inspection),
    ]
