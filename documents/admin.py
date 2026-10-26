from django.contrib import admin

from .models import DocumentTemplate


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'kind', 'is_fixed', 'source_filename')
    list_filter = ('kind', 'is_fixed')
    search_fields = ('code', 'title', 'source_filename', 'body')
    readonly_fields = ('code',)
