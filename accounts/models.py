from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        PLATFORM_ADMIN = 'platform_admin', 'Administrator platforme'
        OWNER = 'owner', 'Vlasnik'
        STAFF = 'staff', 'Zaposleni'

    organization = models.ForeignKey(
        'organizations.Organization',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='members',
    )
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.STAFF,
    )

    class Meta:
        verbose_name = 'korisnik'
        verbose_name_plural = 'korisnici'

    def __str__(self):
        return self.get_full_name() or self.username
