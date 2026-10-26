from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class DayTaskDone(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='day_tasks_done',
    )
    work_date = models.DateField('datum')
    code = models.SlugField(max_length=40)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='day_tasks_done',
    )
    done_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'završen zadatak'
        verbose_name_plural = 'završeni zadaci'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'work_date', 'code'],
                name='uniq_day_task_done',
            ),
        ]

    def __str__(self):
        return f'{self.code} · {self.work_date}'


class HygieneCheck(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'U toku'
        DONE = 'done', 'Završeno'

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='hygiene_checks',
    )
    work_date = models.DateField('datum')
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
    )
    note = models.TextField('napomena', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='hygiene_checks_created',
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='hygiene_checks_completed',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-work_date', '-created_at']
        verbose_name = 'higijena radnog prostora'
        verbose_name_plural = 'higijena radnog prostora'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'work_date'],
                name='uniq_hygiene_per_org_day',
            ),
        ]

    def __str__(self):
        return f'OB-11 {self.work_date} · {self.organization}'

    @property
    def done_count(self):
        return self.lines.filter(is_done=True).count()

    @property
    def total_count(self):
        return self.lines.count()

    @property
    def required_done_count(self):
        return self.lines.filter(is_required=True, is_done=True).count()

    @property
    def required_total_count(self):
        return self.lines.filter(is_required=True).count()

    @property
    def required_done(self):
        return not self.lines.filter(is_required=True, is_done=False).exists()


class HygieneLine(models.Model):
    class Cadence(models.TextChoices):
        DAILY = 'SP', 'Svakodnevno'
        WEEKLY = 'NP', 'Nedeljno'
        MONTHLY = 'MP', 'Mesečno'

    record = models.ForeignKey(
        HygieneCheck,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    code = models.SlugField(max_length=40)
    label = models.CharField(max_length=200)
    cadence = models.CharField(max_length=2, choices=Cadence.choices)
    is_required = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='hygiene_lines_done',
    )

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'stavka higijene'
        verbose_name_plural = 'stavke higijene'
        constraints = [
            models.UniqueConstraint(
                fields=['record', 'code'],
                name='uniq_hygiene_line_code',
            ),
        ]

    def __str__(self):
        return self.label


class TaskDefinition(models.Model):
    """Globalni katalog obaveze. Prazna lista delatnosti važi za sve delatnosti."""

    class Kind(models.TextChoices):
        CONFIRM = 'confirm', 'Potvrda'
        RECORD = 'record', 'Evidencija'
        AUTO = 'auto', 'Automatski'

    class Cadence(models.TextChoices):
        DAILY = 'daily', 'Dnevno'
        WEEKLY = 'weekly', 'Nedeljno'
        MONTHLY = 'monthly', 'Mesečno'
        EVENT = 'event', 'Događaj'

    code = models.SlugField('šifra', max_length=40, unique=True)
    title = models.CharField('naziv', max_length=200)
    kind = models.CharField('vrsta', max_length=16, choices=Kind.choices)
    cadence = models.CharField('ritam', max_length=16, choices=Cadence.choices)
    weekday = models.PositiveSmallIntegerField(
        'dan u nedelji',
        null=True,
        blank=True,
        help_text='0 je ponedeljak, 6 je nedelja. Samo za nedeljni ritam.',
    )
    monthday = models.PositiveSmallIntegerField(
        'dan u mesecu',
        null=True,
        blank=True,
        help_text='Od 1 do 28. Samo za mesečni ritam.',
    )
    due_time = models.TimeField('rok u toku dana', null=True, blank=True)
    document = models.ForeignKey(
        'documents.DocumentTemplate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='task_definitions',
    )
    record_key = models.SlugField(
        'ključ evidencije',
        max_length=40,
        blank=True,
        help_text='hygiene koristi postojeći HygieneCheck. Ostali ključevi čekaju svoj model.',
    )
    hygiene_line_code = models.SlugField(
        'šifra stavke higijene',
        max_length=40,
        blank=True,
        help_text='Kasnija veza nedeljne ili mesečne stavke OB-11. Obrazac se ovde ne menja.',
    )
    auto_key = models.SlugField('ključ automatske provere', max_length=40, blank=True)
    industries = models.ManyToManyField(
        'organizations.Industry',
        blank=True,
        related_name='task_definitions',
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField('aktivna definicija', default=True)

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = 'definicija zadatka'
        verbose_name_plural = 'definicije zadataka'
        constraints = [
            models.CheckConstraint(
                name='taskdef_weekday_range',
                condition=models.Q(weekday__isnull=True) | models.Q(weekday__gte=0, weekday__lte=6),
            ),
            models.CheckConstraint(
                name='taskdef_monthday_range',
                condition=models.Q(monthday__isnull=True) | models.Q(monthday__gte=1, monthday__lte=28),
            ),
            models.CheckConstraint(
                name='taskdef_weekly_has_weekday',
                condition=(
                    (models.Q(cadence='weekly') & models.Q(weekday__isnull=False))
                    | (~models.Q(cadence='weekly') & models.Q(weekday__isnull=True))
                ),
            ),
            models.CheckConstraint(
                name='taskdef_monthly_has_monthday',
                condition=(
                    (models.Q(cadence='monthly') & models.Q(monthday__isnull=False))
                    | (~models.Q(cadence='monthly') & models.Q(monthday__isnull=True))
                ),
            ),
        ]

    def __str__(self):
        return self.title

    def applies_to_industry(self, industry):
        if industry is None or not self.industries.exists():
            return True
        return self.industries.filter(pk=industry.pk).exists()

    def clean(self):
        super().clean()
        if self.kind == self.Kind.AUTO and not self.auto_key:
            raise ValidationError({'auto_key': 'Automatski zadatak mora imati ključ provere.'})
        if self.kind == self.Kind.RECORD and not self.record_key:
            raise ValidationError({'record_key': 'Evidencioni zadatak mora imati ključ evidencije.'})
        if self.hygiene_line_code and self.record_key != 'hygiene':
            raise ValidationError({
                'hygiene_line_code': 'Šifra stavke važi samo za evidenciju higijene.',
            })

    def save(self, *args, **kwargs):
        if not kwargs.get('raw'):
            self.full_clean()
        return super().save(*args, **kwargs)


class OrganizationTask(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='organization_tasks',
    )
    definition = models.ForeignKey(
        TaskDefinition,
        on_delete=models.PROTECT,
        related_name='organization_tasks',
    )
    enabled = models.BooleanField(
        'uključen',
        default=True,
        help_text='Gašenje i ponovno uključivanje ide kroz snimanje ovog reda. Tako ostaje period neaktivnosti.',
    )
    active_from = models.DateField(
        'važi od',
        help_text='Dan od kog ova obaveza važi. Raniji periodi se ne prave.',
    )
    weekday = models.PositiveSmallIntegerField('dan u nedelji', null=True, blank=True)
    monthday = models.PositiveSmallIntegerField('dan u mesecu', null=True, blank=True)
    due_time = models.TimeField('rok u toku dana', null=True, blank=True)

    class Meta:
        ordering = ['definition__sort_order', 'definition__code']
        verbose_name = 'zadatak objekta'
        verbose_name_plural = 'zadaci objekta'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'definition'],
                name='uniq_org_task_definition',
            ),
            models.CheckConstraint(
                name='orgtask_weekday_range',
                condition=models.Q(weekday__isnull=True) | models.Q(weekday__gte=0, weekday__lte=6),
            ),
            models.CheckConstraint(
                name='orgtask_monthday_range',
                condition=models.Q(monthday__isnull=True) | models.Q(monthday__gte=1, monthday__lte=28),
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'enabled'], name='orgtask_org_enabled'),
        ]

    def __str__(self):
        return f'{self.definition.code} · {self.organization}'

    def clean(self):
        super().clean()
        cadence = self.definition.cadence
        if self.weekday is not None and cadence != TaskDefinition.Cadence.WEEKLY:
            raise ValidationError({'weekday': 'Dan u nedelji važi samo za nedeljni ritam.'})
        if self.monthday is not None and cadence != TaskDefinition.Cadence.MONTHLY:
            raise ValidationError({'monthday': 'Dan u mesecu važi samo za mesečni ritam.'})

    def save(self, *args, **kwargs):
        raw = kwargs.get('raw')
        previous_enabled = None
        if self.pk and not raw:
            previous_enabled = (
                OrganizationTask.objects.filter(pk=self.pk)
                .values_list('enabled', flat=True)
                .first()
            )
        if self.active_from is None:
            self.active_from = task_clock_date()
        if not raw:
            self.full_clean()
        super().save(*args, **kwargs)
        if raw:
            return
        _sync_task_activation(self, previous_enabled)


class OrganizationTaskActivation(models.Model):
    """Period u kom je obaveza bila uključena.

    Jedan datum nije dovoljan: između gašenja i ponovnog uključivanja
    ne sme nastati propuštena pojava.
    """

    organization_task = models.ForeignKey(
        OrganizationTask,
        on_delete=models.CASCADE,
        related_name='activations',
    )
    started_on = models.DateField('aktivno od')
    ended_on = models.DateField(
        'aktivno do',
        null=True,
        blank=True,
        help_text='Prazno znači da je obaveza i dalje uključena. Dan gašenja ostaje u periodu.',
    )

    class Meta:
        ordering = ['started_on', 'pk']
        verbose_name = 'period aktivacije'
        verbose_name_plural = 'periodi aktivacije'
        constraints = [
            models.CheckConstraint(
                name='taskact_end_after_start',
                condition=models.Q(ended_on__isnull=True) | models.Q(ended_on__gte=models.F('started_on')),
            ),
            models.UniqueConstraint(
                fields=['organization_task'],
                condition=models.Q(ended_on__isnull=True),
                name='uniq_open_task_activation',
            ),
        ]

    def __str__(self):
        end = self.ended_on.isoformat() if self.ended_on else '…'
        return f'{self.organization_task_id} · {self.started_on} – {end}'


class TaskOccurrence(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Otvoreno'
        DONE = 'done', 'Završeno'
        MISSED = 'missed', 'Propušteno'
        CANCELLED = 'cancelled', 'Otkazano'

    class Result(models.TextChoices):
        PASSED = 'passed', 'Odgovara'
        FAILED = 'failed', 'Ne odgovara'
        NOT_APPLICABLE = 'not_applicable', 'Nije primenljivo'

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='task_occurrences',
    )
    organization_task = models.ForeignKey(
        OrganizationTask,
        on_delete=models.PROTECT,
        related_name='occurrences',
    )
    cadence = models.CharField(
        'ritam pojave',
        max_length=16,
        choices=TaskDefinition.Cadence.choices,
        help_text='Snimak ritma. Periodične pojave su jedinstvene po objektu, definiciji i periodu.',
    )
    period_start = models.DateField('početak perioda')
    period_end = models.DateField('kraj perioda')
    due_at = models.DateTimeField('rok', null=True, blank=True)
    status = models.CharField(
        'status izvršenja',
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
    )
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='task_occurrences_done',
    )
    done_at = models.DateTimeField('završeno', null=True, blank=True)
    result = models.CharField(
        'rezultat kontrole',
        max_length=20,
        choices=Result.choices,
        null=True,
        blank=True,
        help_text='Ne zavisi od statusa. Negativan rezultat i dalje može biti izvršena kontrola.',
    )
    note = models.TextField('napomena', blank=True)
    hygiene_check = models.ForeignKey(
        HygieneCheck,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='task_occurrences',
    )
    legacy_day_task_id = models.PositiveIntegerField(
        'izvorni dnevni zapis',
        null=True,
        blank=True,
        unique=True,
        help_text='DayTaskDone.pk prenet migracijom. Služi da se isti zapis ne prenese dva puta.',
    )

    class Meta:
        ordering = ['-period_start', 'organization_task_id', 'id']
        verbose_name = 'pojava zadatka'
        verbose_name_plural = 'pojave zadataka'
        constraints = [
            models.CheckConstraint(
                name='taskocc_period_order',
                condition=models.Q(period_end__gte=models.F('period_start')),
            ),
            models.UniqueConstraint(
                fields=['organization', 'organization_task', 'period_start'],
                condition=models.Q(cadence__in=['daily', 'weekly', 'monthly']),
                name='uniq_periodic_task_occurrence',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'status', 'period_start'], name='taskocc_org_status_period'),
        ]

    def __str__(self):
        return f'{self.organization_task.definition.code} · {self.period_start}'

    def clean(self):
        super().clean()
        errors = {}
        if self.organization_task_id and self.organization_id:
            if self.organization_task.organization_id != self.organization_id:
                errors['organization'] = 'Pojava mora pripadati objektu svog zadatka.'
        if self.hygiene_check_id and self.organization_id:
            if self.hygiene_check.organization_id != self.organization_id:
                errors['hygiene_check'] = 'Higijena mora pripadati istom objektu.'
        if self.period_start and self.period_end and self.period_end < self.period_start:
            errors['period_end'] = 'Kraj perioda ne može biti pre početka.'
        if self.status == self.Status.DONE and self.done_at is None:
            errors['done_at'] = 'Završena pojava mora imati vreme izvršenja.'
        if self.status == self.Status.CANCELLED:
            if self.done_at is not None or self.done_by_id is not None:
                errors['status'] = 'Otkazana pojava ne sme imati izvršioca.'
            if self.result in (self.Result.PASSED, self.Result.FAILED):
                errors['result'] = 'Otkazana pojava ne sme imati ishod kontrole.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not kwargs.get('raw'):
            if self.organization_task_id and not self.cadence:
                self.cadence = self.organization_task.definition.cadence
            self.full_clean()
        return super().save(*args, **kwargs)


class GoodsReceipt(models.Model):
    """Jedan list OB-15. Završetak i verifikacija su odvojene radnje.

    Tok završetka i verifikacije je u ops.receiving. Model ne da da se
    gotov zapis prepravi.
    """

    class Status(models.TextChoices):
        OPEN = 'open', 'U toku'
        DONE = 'done', 'Završeno'
        CANCELLED = 'cancelled', 'Otkazano'

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='goods_receipts',
    )
    received_on = models.DateField('datum prijema')
    status = models.CharField(
        'status izvršenja',
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='goods_receipts_created',
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='goods_receipts_completed',
    )
    completed_at = models.DateTimeField('završeno', null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='goods_receipts_cancelled',
    )
    cancelled_at = models.DateTimeField('otkazano', null=True, blank=True)
    cancellation_reason = models.CharField(
        'razlog otkazivanja',
        max_length=255,
        blank=True,
    )
    task_occurrence = models.OneToOneField(
        TaskOccurrence,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='goods_receipt',
    )
    verified_on = models.DateField('datum verifikacije', null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='goods_receipts_verified',
    )
    verifier_role = models.CharField('funkcija', max_length=120, blank=True)
    verified_at = models.DateTimeField('vreme verifikacije', null=True, blank=True)

    class Meta:
        ordering = ['-received_on', '-id']
        verbose_name = 'prijem sirovina'
        verbose_name_plural = 'prijemi sirovina'
        indexes = [
            models.Index(fields=['organization', 'received_on'], name='goodsreceipt_org_date'),
        ]

    def __str__(self):
        return f'OB-15 {self.received_on} · {self.organization}'

    def control_result(self):
        """Ishod robe za završen prijem. Otkazan prijem nema ishod kontrole."""
        if not self.pk or self.status == self.Status.CANCELLED:
            return None
        lines = list(self.lines.all())
        if not lines or any(not line.is_complete() for line in lines):
            return None
        failed = any(
            line.visual_check == GoodsReceiptLine.Check.NOT_OK
            or line.product_safety == GoodsReceiptLine.Check.NOT_OK
            for line in lines
        )
        if failed:
            return TaskOccurrence.Result.FAILED
        return TaskOccurrence.Result.PASSED

    def clean(self):
        super().clean()
        errors = {}
        if self.task_occurrence_id and self.organization_id:
            if self.task_occurrence.organization_id != self.organization_id:
                errors['task_occurrence'] = 'Prijem i zadatak moraju pripadati istom objektu.'
        if self.status == self.Status.DONE:
            if self.completed_by_id is None:
                errors['completed_by'] = 'Završen prijem mora imati izvršioca.'
            if self.completed_at is None:
                errors['completed_at'] = 'Završen prijem mora imati vreme završetka.'
            if self.control_result() is None:
                errors['status'] = 'Završen prijem mora imati potpuno popunjene stavke.'
        if self.status == self.Status.CANCELLED:
            if self.cancelled_by_id is None:
                errors['cancelled_by'] = 'Otkazan prijem mora imati ko je otkazao.'
            if self.cancelled_at is None:
                errors['cancelled_at'] = 'Otkazan prijem mora imati vreme otkazivanja.'
            if self.completed_by_id is not None or self.completed_at is not None:
                errors['status'] = 'Otkazan prijem ne sme biti označen kao završen.'
        if self._verification_started():
            if self.status != self.Status.DONE:
                errors['verified_by'] = 'Verifikacija važi samo za završen prijem.'
            elif not self._verification_complete():
                errors['verified_by'] = 'Verifikacija se upisuje cela: datum, lice, funkcija i vreme.'
            elif self.verified_by_id == self.completed_by_id:
                errors['verified_by'] = 'Izvršilac ne može da verifikuje sopstveni prijem.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not kwargs.get('raw'):
            self._reject_locked_changes()
            self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in (self.Status.DONE, self.Status.CANCELLED):
            raise ValidationError('Završen ili otkazan prijem se ne briše.')
        return super().delete(*args, **kwargs)

    def _verification_started(self):
        return any((
            self.verified_on,
            self.verified_by_id,
            (self.verifier_role or '').strip(),
            self.verified_at,
        ))

    def _verification_complete(self):
        return all((
            self.verified_on,
            self.verified_by_id,
            (self.verifier_role or '').strip(),
            self.verified_at,
        ))

    def _reject_locked_changes(self):
        if not self.pk:
            return
        previous = GoodsReceipt.objects.filter(pk=self.pk).first()
        if previous is None:
            return
        if previous.status == self.Status.CANCELLED:
            if self.status != self.Status.CANCELLED:
                raise ValidationError('Otkazan prijem se ne otvara ponovo.')
            changed = (
                previous.organization_id != self.organization_id
                or previous.received_on != self.received_on
                or previous.created_by_id != self.created_by_id
                or previous.completed_by_id != self.completed_by_id
                or previous.completed_at != self.completed_at
                or previous.cancelled_by_id != self.cancelled_by_id
                or previous.cancelled_at != self.cancelled_at
                or (previous.cancellation_reason or '') != (self.cancellation_reason or '')
                or previous.task_occurrence_id != self.task_occurrence_id
                or previous.verified_on != self.verified_on
                or previous.verified_by_id != self.verified_by_id
                or (previous.verifier_role or '') != (self.verifier_role or '')
                or previous.verified_at != self.verified_at
            )
            if changed:
                raise ValidationError('Otkazan prijem se ne menja.')
            return
        if previous.status != self.Status.DONE:
            return
        if self.status != self.Status.DONE:
            raise ValidationError('Završen prijem se ne otvara ponovo.')
        frozen = (
            previous.organization_id != self.organization_id
            or previous.received_on != self.received_on
            or previous.created_by_id != self.created_by_id
            or previous.completed_by_id != self.completed_by_id
            or previous.completed_at != self.completed_at
            or previous.task_occurrence_id != self.task_occurrence_id
            or previous.cancelled_by_id != self.cancelled_by_id
            or previous.cancelled_at != self.cancelled_at
            or (previous.cancellation_reason or '') != (self.cancellation_reason or '')
        )
        if frozen:
            raise ValidationError('Završen prijem se ne menja.')
        if previous._verification_started():
            changed = (
                previous.verified_on != self.verified_on
                or previous.verified_by_id != self.verified_by_id
                or (previous.verifier_role or '') != (self.verifier_role or '')
                or previous.verified_at != self.verified_at
            )
            if changed:
                raise ValidationError('Verifikacija završenog prijema se ne menja.')


class GoodsReceiptLine(models.Model):
    class Check(models.TextChoices):
        OK = 'ok', 'Ispravno'
        NOT_OK = 'not_ok', 'Nije ispravno'

    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    sort_order = models.PositiveSmallIntegerField('redosled', default=0)
    raw_material = models.CharField('sirovina', max_length=200, blank=True)
    manufacturer = models.CharField('proizvođač', max_length=200, blank=True)
    quantity = models.CharField('količina', max_length=80, blank=True)
    visual_check = models.CharField(
        'vizuelna kontrola',
        max_length=16,
        choices=Check.choices,
        blank=True,
    )
    product_safety = models.CharField(
        'bezbednost proizvoda',
        max_length=16,
        choices=Check.choices,
        blank=True,
    )
    note = models.TextField('napomena', blank=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'stavka prijema'
        verbose_name_plural = 'stavke prijema'
        constraints = [
            models.CheckConstraint(
                name='goodsline_visual_check',
                condition=models.Q(visual_check__in=['', 'ok', 'not_ok']),
            ),
            models.CheckConstraint(
                name='goodsline_product_safety',
                condition=models.Q(product_safety__in=['', 'ok', 'not_ok']),
            ),
        ]

    def __str__(self):
        return self.raw_material or 'Stavka prijema'

    def is_complete(self):
        return bool(
            (self.raw_material or '').strip()
            and (self.manufacturer or '').strip()
            and (self.quantity or '').strip()
            and self.visual_check in (self.Check.OK, self.Check.NOT_OK)
            and self.product_safety in (self.Check.OK, self.Check.NOT_OK)
        )

    def save(self, *args, **kwargs):
        if not kwargs.get('raw'):
            self._reject_locked_receipt()
            self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.goods_receipt_id and self.goods_receipt.status != GoodsReceipt.Status.OPEN:
            raise ValidationError('Stavka zaključanog prijema se ne briše.')
        return super().delete(*args, **kwargs)

    def _reject_locked_receipt(self):
        receipt_ids = []
        if self.pk:
            previous_id = (
                GoodsReceiptLine.objects.filter(pk=self.pk)
                .values_list('goods_receipt_id', flat=True)
                .first()
            )
            if previous_id:
                receipt_ids.append(previous_id)
        if self.goods_receipt_id:
            receipt_ids.append(self.goods_receipt_id)
        if GoodsReceipt.objects.filter(
            pk__in=receipt_ids,
        ).exclude(status=GoodsReceipt.Status.OPEN).exists():
            raise ValidationError('Stavka zaključanog prijema se ne menja.')


class ColdSpot(models.Model):
    """Merna tačka za ručni unos temperature (OB-10). Kasnije može vezati IoT senzor."""

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='cold_spots',
    )
    group_name = models.CharField('grupa', max_length=80)
    label = models.CharField('mesto', max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'merna tačka'
        verbose_name_plural = 'merne tačke'
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'group_name', 'label'],
                name='uniq_cold_spot_place',
            ),
        ]

    def __str__(self):
        return f'{self.group_name} · {self.label}'


class TemperatureReading(models.Model):
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='temperature_readings',
    )
    cold_spot = models.ForeignKey(
        ColdSpot,
        on_delete=models.PROTECT,
        related_name='readings',
    )
    work_date = models.DateField('datum')
    value_c = models.DecimalField('temperatura °C', max_digits=5, decimal_places=1)
    min_c = models.DecimalField('min °C', max_digits=5, decimal_places=1)
    max_c = models.DecimalField('max °C', max_digits=5, decimal_places=1)
    is_within_limits = models.BooleanField('u granicama')
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='temperature_readings',
    )
    recorded_at = models.DateTimeField('upisano')
    corrective_action = models.TextField('korektivna mera', blank=True)
    corrective_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='temperature_correctives',
    )
    corrective_at = models.DateTimeField('korektivna mera upisana', null=True, blank=True)

    class Meta:
        ordering = ['-recorded_at', '-id']
        verbose_name = 'merenje temperature'
        verbose_name_plural = 'merenja temperature'
        indexes = [
            models.Index(
                fields=['organization', 'work_date'],
                name='tempread_org_date',
            ),
        ]

    def __str__(self):
        return f'{self.cold_spot} · {self.value_c} °C'

    @property
    def alert_open(self):
        return not self.is_within_limits and not (self.corrective_action or '').strip()

    def clean(self):
        super().clean()
        errors = {}
        if self.cold_spot_id and self.organization_id:
            if self.cold_spot.organization_id != self.organization_id:
                errors['cold_spot'] = 'Merna tačka mora pripadati objektu.'
        if self.value_c is not None and self.min_c is not None and self.max_c is not None:
            within = self.min_c <= self.value_c <= self.max_c
            if self.is_within_limits is None:
                self.is_within_limits = within
            elif self.is_within_limits != within:
                errors['value_c'] = 'Status granica ne odgovara upisanoj temperaturi.'
        if (self.corrective_action or '').strip():
            if self.is_within_limits:
                errors['corrective_action'] = 'Korektivna mera važi samo za merenje van granica.'
            if self.corrective_by_id is None:
                errors['corrective_by'] = 'Korektivna mera mora imati izvršioca.'
            if self.corrective_at is None:
                errors['corrective_at'] = 'Korektivna mera mora imati vreme.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not kwargs.get('raw'):
            if (
                self.value_c is not None
                and self.min_c is not None
                and self.max_c is not None
                and self.is_within_limits is None
            ):
                self.is_within_limits = self.min_c <= self.value_c <= self.max_c
            self.full_clean()
        return super().save(*args, **kwargs)


def task_clock_date():
    return timezone.localtime(timezone.now()).date()


def _sync_task_activation(org_task, previous_enabled):
    today = task_clock_date()
    if previous_enabled is None:
        if org_task.enabled:
            _open_task_activation(org_task, org_task.active_from)
        return
    if previous_enabled and not org_task.enabled:
        _close_task_activation(org_task, today)
    elif not previous_enabled and org_task.enabled:
        _open_task_activation(org_task, today)


def _open_task_activation(org_task, started_on):
    if org_task.activations.filter(ended_on__isnull=True).exists():
        return
    OrganizationTaskActivation.objects.create(
        organization_task=org_task,
        started_on=started_on,
    )


def _close_task_activation(org_task, on_date):
    window = org_task.activations.filter(ended_on__isnull=True).order_by('started_on').first()
    if window is None:
        return
    window.ended_on = on_date
    window.save(update_fields=['ended_on'])
