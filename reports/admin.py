# apps/reports/admin.py

from django.contrib import admin

from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "type",
        "date_from",
        "date_to",
        "generated_by",
        "created_at",
    )
    list_filter = ("type", "date_from", "date_to", "created_at")
    search_fields = ("id", "generated_by__phone", "generated_by__email")
    readonly_fields = ("created_at", "pdf_file")
