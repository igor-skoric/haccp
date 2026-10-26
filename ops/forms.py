from django import forms

from ops.models import ColdSpot, GoodsReceiptLine


class TemperatureReadingForm(forms.Form):
    cold_spot = forms.ModelChoiceField(
        label='Merna tačka',
        queryset=ColdSpot.objects.none(),
        widget=forms.Select(attrs={'class': 'input'}),
    )
    value_c = forms.DecimalField(
        label='Temperatura (°C)',
        max_digits=5,
        decimal_places=1,
        widget=forms.NumberInput(attrs={'class': 'input', 'step': '0.1'}),
    )
    corrective_action = forms.CharField(
        label='Korektivna mera (ako je van granica)',
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 2}),
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields['cold_spot'].queryset = ColdSpot.objects.filter(
                organization=organization,
                is_active=True,
            )


class CorrectiveActionForm(forms.Form):
    corrective_action = forms.CharField(
        label='Korektivna mera',
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3}),
    )


class ReceivingVerifyForm(forms.Form):
    verifier_role = forms.CharField(
        label='Funkcija',
        max_length=120,
        widget=forms.TextInput(attrs={'class': 'input', 'placeholder': 'npr. Odgovorno lice'}),
    )


class ReceivingCancelForm(forms.Form):
    cancellation_reason = forms.CharField(
        label='Razlog (opciono)',
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'input',
            'placeholder': 'npr. Otvoreno greškom',
        }),
    )
    confirm_cancel = forms.BooleanField(
        label='Potvrđujem otkazivanje',
        required=True,
        error_messages={'required': 'Potvrdi otkazivanje da nastaviš.'},
    )


class GoodsReceiptLineForm(forms.Form):
    raw_material = forms.CharField(
        label='Sirovina',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'input'}),
    )
    manufacturer = forms.CharField(
        label='Proizvođač',
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'input'}),
    )
    quantity = forms.CharField(
        label='Količina',
        max_length=80,
        widget=forms.TextInput(attrs={'class': 'input'}),
    )
    visual_check = forms.ChoiceField(
        label='Vizuelna kontrola',
        choices=GoodsReceiptLine.Check.choices,
        widget=forms.Select(attrs={'class': 'input'}),
    )
    product_safety = forms.ChoiceField(
        label='Bezbednost proizvoda',
        choices=GoodsReceiptLine.Check.choices,
        widget=forms.Select(attrs={'class': 'input'}),
    )
    note = forms.CharField(
        label='Napomena',
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 2}),
    )
