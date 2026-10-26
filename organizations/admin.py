from django.contrib import admin

from .models import Industry, Organization, OrganizationSettings


@admin.register(Industry)
class IndustryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'sort_order')
    prepopulated_fields = {'code': ('name',)}
    search_fields = ('name', 'code')


class OrganizationSettingsInline(admin.StackedInline):
    model = OrganizationSettings
    can_delete = False
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'industry', 'slug', 'created_at')
    list_filter = ('industry',)
    search_fields = ('name', 'slug')
    readonly_fields = ('created_at',)
    inlines = (OrganizationSettingsInline,)
