"""labels 应用表单：标签模板维护 + 打印参数。"""

from django import forms

from .models import LabelTemplate
from .services import MAX_COPIES, make_printer_key


class BootstrapFormMixin:
    """给所有字段自动加上 Bootstrap 样式，保持页面风格统一。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


class LabelTemplateForm(BootstrapFormMixin, forms.ModelForm):
    """标签模板新增/编辑表单。"""

    class Meta:
        model = LabelTemplate
        fields = (
            "name", "description", "width_mm", "height_mm", "font_name",
            "include_qr", "qr_content",
            "show_value", "show_package", "show_stock", "show_location",
            "show_batch", "show_manufacturer", "show_category",
            "default_copies", "is_default", "is_active",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "width_mm": forms.NumberInput(attrs={"step": "0.1", "min": "10", "max": "300"}),
            "height_mm": forms.NumberInput(attrs={"step": "0.1", "min": "10", "max": "300"}),
            "default_copies": forms.NumberInput(attrs={"step": "1", "min": "1", "max": "100"}),
        }

    def _get_validation_exclusions(self):
        # 默认模板互斥由 Model.save() 处理（保存前先取消旧默认），
        # 这里跳过 is_default 的条件唯一约束校验，避免同时勾选默认时误报。
        exclude = super()._get_validation_exclusions()
        exclude.add("is_default")
        return exclude

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("include_qr") and not cleaned.get("qr_content"):
            self.add_error("qr_content", "启用二维码时请选择二维码内容。")
        return cleaned


class LabelPrintSettingsForm(BootstrapFormMixin, forms.Form):
    """打印参数：模板、每个元件份数、目标打印机。

    打印机列表由视图调用 ``services.list_printers`` 后通过 ``printers``
    传入：无打印机环境下仍可渲染表单并给出提示。
    """

    template = forms.ModelChoiceField(
        label="标签模板",
        queryset=LabelTemplate.objects.none(),
        empty_label=None,
        help_text="仅显示启用中的模板",
    )
    copies = forms.IntegerField(
        label="每个元件份数",
        min_value=1,
        max_value=MAX_COPIES,
        initial=1,
        help_text=f"单次最多打印 {MAX_COPIES} 份/元件",
    )
    printer = forms.ChoiceField(
        label="打印机",
        required=False,
        choices=(),
        help_text="留空时使用默认打印机",
    )

    def __init__(self, *args, printers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = LabelTemplate.objects.filter(is_active=True)
        choices = [("", "自动选择默认打印机")]
        for printer in printers or []:
            choices.append((
                printer.get("key") or make_printer_key(printer),
                f"{printer.get('name', '未命名打印机')}（{printer.get('type_label', '其他')}）",
            ))
        self.fields["printer"].choices = choices
