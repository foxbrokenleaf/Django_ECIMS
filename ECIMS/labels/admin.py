"""labels 应用后台配置。"""

from django.contrib import admin

from .models import LabelPrintRecord, LabelTemplate


@admin.register(LabelTemplate)
class LabelTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "name", "width_mm", "height_mm", "font_name", "include_qr",
        "default_copies", "is_default", "is_active", "updated_at",
    )
    list_filter = ("is_active", "is_default", "include_qr")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("基本信息", {
            "fields": ("name", "description", "is_default", "is_active"),
        }),
        ("尺寸与字体", {
            "fields": ("width_mm", "height_mm", "font_name", "default_copies"),
        }),
        ("二维码", {
            "fields": ("include_qr", "qr_content"),
        }),
        ("打印字段", {
            "fields": (
                "show_value", "show_package", "show_stock", "show_location",
                "show_batch", "show_manufacturer", "show_category",
            ),
        }),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(LabelPrintRecord)
class LabelPrintRecordAdmin(admin.ModelAdmin):
    list_display = (
        "component_name", "component_model", "template_name", "copies",
        "printer_name", "status", "operator", "created_at",
    )
    list_filter = ("status", "template", "created_at")
    search_fields = (
        "component_name", "component_model", "component_uid",
        "template_name", "printer_name",
    )
    list_select_related = ("component", "template", "operator")
    date_hierarchy = "created_at"
    readonly_fields = (
        "batch_id", "component", "component_name", "component_model",
        "component_uid", "template", "template_name", "copies",
        "printer_name", "status", "message", "operator", "created_at",
    )

    def has_add_permission(self, request):
        # 打印记录由业务页面生成，后台不手工新增
        return False

