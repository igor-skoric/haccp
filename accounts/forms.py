from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import transaction

from ops.scheduling import assign_organization_tasks
from ops.temperatures import ensure_cold_spots
from organizations.models import Industry, Organization, OrganizationSettings

from .models import User


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Korisničko ime'
        self.fields['password'].label = 'Lozinka'
        for field in self.fields.values():
            field.widget.attrs['class'] = 'input'


class RegistrationForm(forms.Form):
    organization_name = forms.CharField(label='Naziv objekta', max_length=200)
    industry = forms.ModelChoiceField(
        label='Delatnost',
        queryset=Industry.objects.none(),
        empty_label='Izaberite delatnost',
    )
    first_name = forms.CharField(label='Ime', max_length=150)
    last_name = forms.CharField(label='Prezime', max_length=150)
    username = forms.CharField(
        label='Korisničko ime',
        max_length=150,
        validators=[UnicodeUsernameValidator()],
    )
    email = forms.EmailField(label='E-pošta', required=False)
    password1 = forms.CharField(label='Lozinka', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Ponovite lozinku', widget=forms.PasswordInput)

    def __init__(self, *args, industry_code=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['industry'].queryset = Industry.objects.order_by('sort_order', 'name')
        if industry_code and not self.is_bound:
            industry = Industry.objects.filter(code=industry_code).first()
            if industry:
                self.fields['industry'].initial = industry.pk
        for field in self.fields.values():
            field.widget.attrs['class'] = 'input'

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Korisničko ime je zauzeto.')
        return username

    def clean_password1(self):
        password = self.cleaned_data['password1']
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Lozinke se ne poklapaju.')
        return cleaned

    def save(self):
        data = self.cleaned_data
        with transaction.atomic():
            organization = Organization(
                name=data['organization_name'],
                industry=data['industry'],
            )
            organization.save()
            user = User(
                username=data['username'],
                email=data.get('email') or '',
                first_name=data['first_name'],
                last_name=data['last_name'],
                organization=organization,
                role=User.Role.OWNER,
            )
            user.set_password(data['password1'])
            user.save()
            OrganizationSettings.objects.get_or_create(organization=organization)
            assign_organization_tasks(organization)
            ensure_cold_spots(organization)
        return user
