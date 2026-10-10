from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Category, Component, StockRecord


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "is_active", "created_at")
    list_filter = ("is_active", "parent")
    search_fields = ("name", "code")


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = (
        "model_number", "name", "category", "package",
        "stock_quantity", "safety_stock", "is_low_stock", "is_active",
    )
    list_filter = ("category", "mount_type", "is_active", "manufacturer")
    search_fields = ("name", "model_number", "value", "description")
    readonly_fields = ("stock_quantity", "created_at", "updated_at")
    autocomplete_fields = ("category",)
    fieldsets = (
        ("基本信息", {
            "fields": ("name", "model_number", "category", "manufacturer", "description")
        }),
        ("规格参数", {
            "fields": ("package", "mount_type", "value", "tolerance",
                       "voltage_rating", "power_rating", "extra_specs")
        }),
        ("库存", {
            "fields": ("stock_quantity", "safety_stock", "unit",
                       "storage_location", "batch_number")
        }),
        ("采购", {"fields": ("reference_price", "supplier")}),
        ("附件", {"fields": ("datasheet", "image")}),
        ("状态与审计", {
            "fields": ("is_active", "created_by", "created_at", "updated_at")
        }),
    )


@admin.register(StockRecord)
class StockRecordAdmin(admin.ModelAdmin):
    list_display = (
        "component", "record_type", "quantity",
        "quantity_after", "operator", "created_at",
    )
    list_filter = ("record_type", "created_at")
    search_fields = ("component__name", "component__model_number", "batch_number")
    readonly_fields = ("quantity_after", "created_at")