from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def unique_organization_slug(name):
    base = (slugify(name) or 'objekat')[:50]
    slug = base
    number = 2
    while Organization.objects.filter(slug=slug).exists():
        suffix = f'-{number}'
        slug = f'{base[:50 - len(suffix)]}{suffix}'
        number += 1
    return slug


class Industry(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField('naziv', max_length=120)
    description = models.TextField('opis', blank=True)
    sort_order = models.PositiveSmallIntegerField('redosled', default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'delatnost'
        verbose_name_plural = 'delatnosti'

    def __str__(self):
        return self.name


class Organization(models.Model):
    name = models.CharField('naziv', max_length=200)
    slug = models.SlugField(max_length=60, unique=True, blank=True)
    industry = models.ForeignKey(
        Industry,
        verbose_name='delatnost',
        on_delete=models.PROTECT,
        related_name='organizations',
    )
    created_at = models.DateTimeField('kreirano', auto_now_add=True)
    tasks_started_on = models.DateField(
        'zadaci važe od',
        help_text='Dan od kog objekat koristi zadatke. Raniji periodi se ne prave.',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'klijent'
        verbose_name_plural = 'klijenti'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_organization_slug(self.name)
        if self.tasks_started_on is None:
            self.tasks_started_on = timezone.localdate()
        super().save(*args, **kwargs)


class OrganizationSettings(models.Model):
    organization = models.OneToOneField(
        Organization,
        verbose_name='objekat',
        on_delete=models.CASCADE,
        related_name='settings',
    )
    alarms_enabled = models.BooleanField('alarmi uključeni', default=True)
    temp_min_c = models.DecimalField(
        'donja granica (°C)',
        max_digits=4,
        decimal_places=1,
        default=Decimal('2.0'),
        validators=[MinValueValidator(Decimal('-40')), MaxValueValidator(Decimal('40'))],
    )
    temp_max_c = models.DecimalField(
        'gornja granica (°C)',
        max_digits=4,
        decimal_places=1,
        default=Decimal('8.0'),
        validators=[MinValueValidator(Decimal('-40')), MaxValueValidator(Decimal('40'))],
    )
    sensor_stale_minutes = models.PositiveSmallIntegerField(
        'kasnjenje senzora (min)',
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(180)],
    )
    updated_at = models.DateTimeField('izmenjeno', auto_now=True)

    class Meta:
        verbose_name = 'podešavanja objekta'
        verbose_name_plural = 'podešavanja objekata'

    def __str__(self):
        return f'Podešavanja · {self.organization}'
