from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('HACCP', {'fields': ('organization', 'role')}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ('HACCP', {'fields': ('organization', 'role')}),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'organization', 'role', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser', 'organization__industry')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'organization__name')
