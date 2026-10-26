from django import forms

from ops.models import OrganizationTask, TaskDefinition

from .models import OrganizationSettings

WEEKDAYS = (
    (0, 'Ponedeljak'),
    (1, 'Utorak'),
    (2, 'Sreda'),
    (3, 'Četvrtak'),
    (4, 'Petak'),
    (5, 'Subota'),
    (6, 'Nedelja'),
)


class _SettingsForm(forms.ModelForm):
    class Meta:
        model = OrganizationSettings
        fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'alarms_enabled':
                continue
            field.widget.attrs['class'] = 'input'


class AlarmsSettingsForm(_SettingsForm):
    class Meta(_SettingsForm.Meta):
        fields = ('alarms_enabled',)


class TemperatureSettingsForm(_SettingsForm):
    class Meta(_SettingsForm.Meta):
        fields = ('temp_min_c', 'temp_max_c')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['temp_min_c'].widget.attrs.update({'step': '0.1', 'inputmode': 'decimal'})
        self.fields['temp_max_c'].widget.attrs.update({'step': '0.1', 'inputmode': 'decimal'})

    def clean(self):
        cleaned = super().clean()
        low = cleaned.get('temp_min_c')
        high = cleaned.get('temp_max_c')
        if low is not None and high is not None and low >= high:
            self.add_error('temp_max_c', 'Gornja granica mora biti viša od donje.')
        return cleaned


class OrganizationTaskSettingsForm(forms.ModelForm):
    weekday = forms.TypedChoiceField(
        label='Dan u nedelji',
        choices=WEEKDAYS,
        coerce=int,
        empty_value=None,
        required=False,
        widget=forms.Select(attrs={'class': 'input'}),
    )
    monthday = forms.IntegerField(
        label='Dan u mesecu',
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'input',
            'min': '1',
            'max': '28',
            'inputmode': 'numeric',
        }),
    )
    due_time = forms.TimeField(
        label='Vreme izvršenja',
        required=False,
        input_formats=['%H:%M', '%H:%M:%S'],
        widget=forms.TimeInput(format='%H:%M', attrs={'class': 'input', 'type': 'time'}),
    )

    class Meta:
        model = OrganizationTask
        fields = ('enabled', 'weekday', 'monthday', 'due_time')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cadence = self.instance.definition.cadence
        self.fields['enabled'].required = False
        self.fields['enabled'].label = 'Uključen'
        if cadence != TaskDefinition.Cadence.WEEKLY:
            self.fields.pop('weekday')
        else:
            self.fields['weekday'].required = True
            if not self.is_bound and self.instance.weekday is None:
                self.initial['weekday'] = self.instance.definition.weekday
        if cadence != TaskDefinition.Cadence.MONTHLY:
            self.fields.pop('monthday')
        else:
            self.fields['monthday'].required = True
            if not self.is_bound and self.instance.monthday is None:
                self.initial['monthday'] = self.instance.definition.monthday
        if (
            not self.is_bound
            and self.instance.due_time is None
            and self.instance.definition.due_time is not None
        ):
            self.initial['due_time'] = self.instance.definition.due_time

    def clean_weekday(self):
        value = self.cleaned_data.get('weekday')
        if value is None:
            raise forms.ValidationError('Izaberi dan u nedelji.')
        if value < 0 or value > 6:
            raise forms.ValidationError('Dan u nedelji mora biti od ponedeljka do nedelje.')
        return value

    def clean_monthday(self):
        value = self.cleaned_data.get('monthday')
        if value is None:
            raise forms.ValidationError('Upiši dan u mesecu.')
        if value < 1 or value > 28:
            raise forms.ValidationError('Dan u mesecu mora biti od 1 do 28.')
        return value


class SensorSettingsForm(_SettingsForm):
    class Meta(_SettingsForm.Meta):
        fields = ('sensor_stale_minutes',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sensor_stale_minutes'].widget.attrs.update({'min': '1', 'max': '180'})
