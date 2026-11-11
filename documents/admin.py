from django.contrib import admin

from .models import DocumentTemplate, InspectionRecord


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'kind', 'is_fixed', 'source_filename')
    list_filter = ('kind', 'is_fixed')
    search_fields = ('code', 'title', 'source_filename', 'body')
    readonly_fields = ('code', 'checklist')


@admin.register(InspectionRecord)
class InspectionRecordAdmin(admin.ModelAdmin):
    list_display = ('organization', 'template', 'status', 'created_at', 'completed_at')
    list_filter = ('template', 'status')
    search_fields = ('organization__name', 'template__code', 'remarks')
    readonly_fields = (
        'snapshot',
        'created_at',
        'updated_at',
        'completed_at',
        'completed_by',
    )
