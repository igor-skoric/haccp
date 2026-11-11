from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class DocumentTemplate(models.Model):
    class Kind(models.TextChoices):
        HP = 'HP', 'HACCP plan'
        PR = 'PR', 'Procedura'
        UP = 'UP', 'Uputstvo'
        OB = 'OB', 'Obrazac'
        IN = 'IN', 'Inspekcija'

    code = models.CharField('šifra', max_length=12, unique=True)
    kind = models.CharField('vrsta', max_length=2, choices=Kind.choices)
    title = models.CharField('naziv', max_length=200)
    source_filename = models.CharField('izvorni fajl', max_length=255)
    body = models.TextField('tekst', blank=True)
    is_fixed = models.BooleanField('isti za sve', default=True)
    note = models.TextField('napomena', blank=True)
    checklist = models.JSONField('kontrolna lista', blank=True, default=dict)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = 'šablon dokumenta'
        verbose_name_plural = 'šabloni dokumenata'

    def __str__(self):
        return f'{self.code} {self.title}'


class InspectionRecord(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'U toku'
        DONE = 'done', 'Završena'

    organization = models.ForeignKey(
        'organizations.Organization',
        verbose_name='objekat',
        on_delete=models.CASCADE,
        related_name='inspection_records',
    )
    template = models.ForeignKey(
        DocumentTemplate,
        verbose_name='lista',
        on_delete=models.CASCADE,
        related_name='inspection_records',
    )
    status = models.CharField(
        'status',
        max_length=8,
        choices=Status.choices,
        default=Status.OPEN,
    )
    answers = models.JSONField('odgovori', blank=True, default=dict)
    notes = models.JSONField('napomene', blank=True, default=dict)
    remarks = models.TextField('primedbe i sugestije', blank=True)
    snapshot = models.JSONField('verzija liste', blank=True, default=dict)
    created_at = models.DateTimeField('započeto', auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='započeo',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inspection_runs_started',
    )
    updated_at = models.DateTimeField('izmenjeno', auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='izmenio',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inspection_updates',
    )
    completed_at = models.DateTimeField('završeno', null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='završio',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inspection_runs_completed',
    )

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'kontrola'
        verbose_name_plural = 'kontrole'

    def __str__(self):
        return f'{self.template.code} · {self.organization} · {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if self.pk:
            previous = (
                InspectionRecord.objects.filter(pk=self.pk)
                .values(
                    'status',
                    'answers',
                    'notes',
                    'remarks',
                    'snapshot',
                    'completed_at',
                    'completed_by_id',
                    'organization_id',
                    'template_id',
                )
                .first()
            )
            if previous:
                if self.snapshot != previous['snapshot']:
                    raise ValidationError('Verzija liste se ne menja.')
                if previous['status'] == self.Status.DONE and (
                    self.status != self.Status.DONE
                    or self.answers != previous['answers']
                    or self.notes != previous['notes']
                    or self.remarks != previous['remarks']
                    or self.completed_at != previous['completed_at']
                    or self.completed_by_id != previous['completed_by_id']
                    or self.organization_id != previous['organization_id']
                    or self.template_id != previous['template_id']
                ):
                    raise ValidationError('Završena kontrola je zaključana.')
        super().save(*args, **kwargs)
