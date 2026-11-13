from django.contrib import admin
from .models import DamageApply, InboundApply, OutboundApply


class BaseApplyAdmin(admin.ModelAdmin):
    list_display = ("apply_no", "applicant", "component", "quantity",
                    "status", "reviewer", "created_at", "reviewed_at")
    list_filter = ("status", "created_at")
    search_fields = ("apply_no", "component__name", "component__model_number",
                     "custom_name", "applicant__username")
    readonly_fields = ("apply_no", "reviewer", "reviewed_at", "created_at")
    autocomplete_fields = ("component",)


@admin.register(InboundApply)
class InboundApplyAdmin(BaseApplyAdmin):
    pass


@admin.register(OutboundApply)
class OutboundApplyAdmin(BaseApplyAdmin):
    pass


@admin.register(DamageApply)
class DamageApplyAdmin(BaseApplyAdmin):
    pass