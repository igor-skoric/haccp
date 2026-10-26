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
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = 'šablon dokumenta'
        verbose_name_plural = 'šabloni dokumenata'

    def __str__(self):
        return f'{self.code} {self.title}'
