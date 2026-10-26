import django.db.models.deletion
from django.db import migrations, models


def anchor_organization_tasks(apps, schema_editor):
    """Postojeći objekti ne dobijaju izmišljenih 35 dana unazad.

    Početak ostaje dan ove migracije, već upisan na objektu.
    Postojeće pojave, izvršioci i propušteni zapisi se ne diraju.
    """
    OrganizationTask = apps.get_model('ops', 'OrganizationTask')
    Activation = apps.get_model('ops', 'OrganizationTaskActivation')
    tasks = OrganizationTask.objects.select_related('organization').order_by('pk')
    for task in tasks:
        if task.active_from is None:
            OrganizationTask.objects.filter(pk=task.pk).update(
                active_from=task.organization.tasks_started_on,
            )
            task.active_from = task.organization.tasks_started_on
        if not task.enabled:
            continue
        if Activation.objects.filter(organization_task=task, ended_on__isnull=True).exists():
            continue
        Activation.objects.create(
            organization_task=task,
            started_on=task.active_from,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0004_seed_task_catalog'),
        ('organizations', '0004_tasks_started_on'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizationtask',
            name='active_from',
            field=models.DateField(
                help_text='Dan od kog ova obaveza važi. Raniji periodi se ne prave.',
                null=True,
                verbose_name='važi od',
            ),
        ),
        migrations.CreateModel(
            name='OrganizationTaskActivation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_on', models.DateField(verbose_name='aktivno od')),
                ('ended_on', models.DateField(
                    blank=True,
                    help_text='Prazno znači da je obaveza i dalje uključena. Dan gašenja ostaje u periodu.',
                    null=True,
                    verbose_name='aktivno do',
                )),
                ('organization_task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='activations',
                    to='ops.organizationtask',
                )),
            ],
            options={
                'verbose_name': 'period aktivacije',
                'verbose_name_plural': 'periodi aktivacije',
                'ordering': ['started_on', 'pk'],
            },
        ),
        migrations.AddConstraint(
            model_name='organizationtaskactivation',
            constraint=models.CheckConstraint(
                condition=models.Q(('ended_on__isnull', True), ('ended_on__gte', models.F('started_on')), _connector='OR'),
                name='taskact_end_after_start',
            ),
        ),
        migrations.AddConstraint(
            model_name='organizationtaskactivation',
            constraint=models.UniqueConstraint(
                condition=models.Q(('ended_on__isnull', True)),
                fields=('organization_task',),
                name='uniq_open_task_activation',
            ),
        ),
        migrations.RunPython(anchor_organization_tasks, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='organizationtask',
            name='active_from',
            field=models.DateField(
                help_text='Dan od kog ova obaveza važi. Raniji periodi se ne prave.',
                verbose_name='važi od',
            ),
        ),
        migrations.AlterField(
            model_name='organizationtask',
            name='enabled',
            field=models.BooleanField(
                default=True,
                help_text='Gašenje i ponovno uključivanje ide kroz snimanje ovog reda. Tako ostaje period neaktivnosti.',
                verbose_name='uključen',
            ),
        ),
    ]
