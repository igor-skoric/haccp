from django.contrib import admin

from .models import ColdSpot, HygieneCheck, HygieneLine, TemperatureReading


class HygieneLineInline(admin.TabularInline):
    model = HygieneLine
    extra = 0


@admin.register(HygieneCheck)
class HygieneCheckAdmin(admin.ModelAdmin):
    list_display = ('work_date', 'organization', 'status', 'created_by', 'completed_at')
    list_filter = ('status', 'work_date')
    inlines = [HygieneLineInline]


@admin.register(ColdSpot)
class ColdSpotAdmin(admin.ModelAdmin):
    list_display = ('group_name', 'label', 'organization', 'sort_order', 'is_active')
    list_filter = ('organization', 'is_active')


@admin.register(TemperatureReading)
class TemperatureReadingAdmin(admin.ModelAdmin):
    list_display = (
        'recorded_at',
        'cold_spot',
        'value_c',
        'is_within_limits',
        'organization',
        'recorded_by',
    )
    list_filter = ('organization', 'work_date', 'is_within_limits')
