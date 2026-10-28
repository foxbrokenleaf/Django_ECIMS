"""components 应用表单：元件维护 + 库存变动。"""

from django import forms
from django.core.exceptions import ValidationError

from .models import Category, Component, StockRecord


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


class ComponentForm(BootstrapFormMixin, forms.ModelForm):
    """元件新增/编辑表单；库存数量只能通过出入库流水变更。"""

    initial_stock = forms.IntegerField(
        label="初始入库数量",
        min_value=0,
        required=False,
        initial=0,
        help_text="仅新增时生效，会生成一条入库流水，默认 0",
    )

    class Meta:
        model = Component
        fields = (
            "name", "model_number", "category", "manufacturer", "description",
            "package", "mount_type", "value", "tolerance",
            "voltage_rating", "power_rating", "extra_specs",
            "safety_stock", "unit", "storage_location", "batch_number",
            "reference_price", "supplier",
            "datasheet", "image", "is_active",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "extra_specs": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": '{"温度系数": "±100ppm"}',
            }),
            "reference_price": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["extra_specs"].error_messages["invalid"] = (
            '请输入合法的 JSON，例如 {"温度系数": "±100ppm"}'
        )
        if self.instance.pk:
            # 已存在的元件不允许再填“初始入库”，库存只能走流水
            self.fields.pop("initial_stock")

    def clean(self):
        cleaned = super().clean()
        model_number = cleaned.get("model_number")
        manufacturer = cleaned.get("manufacturer") or ""
        if model_number:
            duplicates = Component.objects.filter(
                model_number=model_number, manufacturer=manufacturer,
            ).exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise ValidationError(
                    f"型号「{model_number}」+ 制造商「{manufacturer or '未填写'}」"
                    "已存在，请直接编辑已有元件。"
                )
        return cleaned


class StockAdjustForm(BootstrapFormMixin, forms.Form):
    """出入库/盘点表单。数量统一按“带符号变动量”写入 StockRecord。"""

    record_type = forms.ChoiceField(label="类型", choices=StockRecord.RecordType.choices)
    quantity = forms.IntegerField(
        label="数量",
        help_text="入库、退料填正数；出库填正数（系统记为负数）；盘点调整可填负数",
    )
    unit_price = forms.DecimalField(
        label="单价", max_digits=12, decimal_places=4, required=False, min_value=0,
    )
    batch_number = forms.CharField(label="批次号", max_length=100, required=False)
    storage_location = forms.CharField(label="存放位置", max_length=100, required=False)
    remark = forms.CharField(
        label="备注", required=False, widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, component=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.component = component
        if component is not None:
            self.fields["batch_number"].initial = component.batch_number
            self.fields["storage_location"].initial = component.storage_location
            self.fields["unit_price"].initial = component.reference_price

    def clean(self):
        cleaned = super().clean()
        record_type = cleaned.get("record_type")
        quantity = cleaned.get("quantity")

        if record_type is None or quantity is None:
            return cleaned
        if quantity == 0:
            raise ValidationError("数量不能为 0")

        positive_only = (
            StockRecord.RecordType.IN,
            StockRecord.RecordType.RETURN,
            StockRecord.RecordType.OUT,
        )
        if record_type in positive_only and quantity < 0:
            raise ValidationError("入库、出库、退料请填写正数数量")
        return cleaned

    def signed_quantity(self):
        """实际写入流水的带符号数量：出库为负，其余按填写值。"""
        quantity = self.cleaned_data["quantity"]
        if self.cleaned_data["record_type"] == StockRecord.RecordType.OUT:
            return -quantity
        return quantity
