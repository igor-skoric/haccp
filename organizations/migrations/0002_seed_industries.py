from django.db import migrations


INDUSTRIES = [
    (
        'kafic',
        'Kafić',
        'Ugostiteljski objekat: prijem namirnica, hlađenje, higijena i dnevni zapisi.',
        1,
    ),
    (
        'poslasticarnica',
        'Poslastičarnica',
        'Poslastice i peciva: vitrine, alergeni i režim pečenja.',
        2,
    ),
    (
        'proizvodnja',
        'Proizvodnja',
        'Proizvodni pogon: radni nalozi, kritične tačke i sledljivost.',
        3,
    ),
]


def seed_industries(apps, schema_editor):
    Industry = apps.get_model('organizations', 'Industry')
    for code, name, description, sort_order in INDUSTRIES:
        Industry.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'description': description,
                'sort_order': sort_order,
            },
        )


def remove_industries(apps, schema_editor):
    Industry = apps.get_model('organizations', 'Industry')
    Industry.objects.filter(code__in=[row[0] for row in INDUSTRIES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('organizations', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_industries, remove_industries),
    ]
