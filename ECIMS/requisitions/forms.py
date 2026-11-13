from django import forms

from components.models import Component
from .models import ApplyStatus, DamageApply, InboundApply, OutboundApply


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.Select):
                w.attrs["class"] = "form-select"
            else:
                w.attrs["class"] = "form-control"


class InboundApplyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = InboundApply
        fields = ("component", "custom_name", "custom_model", "quantity", "reason")
        labels = {
            "component": "库内元件",
            "custom_name": "自定义元件名称（库中没有时填）",
            "custom_model": "自定义型号/料号",
            "reason": "申请理由",
        }
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 2}),
            "custom_name": forms.TextInput(
                attrs={"placeholder": "库中没有时填写，如：STM32F103C8T6"}
            ),
            "custom_model": forms.TextInput(
                attrs={"placeholder": "选填，如：LQFP48"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["component"].queryset = Component.objects.filter(is_active=True)
        self.fields["component"].required = False
        self.fields["custom_name"].required = False
        self.fields["custom_model"].required = False

    def clean(self):
        cleaned = super().clean()
        component = cleaned.get("component")
        custom_name = (cleaned.get("custom_name") or "").strip()
        if not component and not custom_name:
            raise forms.ValidationError("请选择库内元件，或填写自定义元件名称")
        if component and custom_name:
            raise forms.ValidationError("库内元件与自定义名称只能二选一")
        cleaned["custom_name"] = custom_name
        return cleaned


class OutboundApplyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OutboundApply
        fields = ("component", "quantity", "purpose")
        widgets = {"purpose": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["component"].queryset = Component.objects.filter(is_active=True)
        self.fields["component"].required = True

    def clean(self):
        cleaned = super().clean()
        component, quantity = cleaned.get("component"), cleaned.get("quantity")
        if not component:
            raise forms.ValidationError("请选择元件")
        if component and quantity and quantity > component.stock_quantity:
            raise forms.ValidationError(
                f"库存不足：当前库存 {component.stock_quantity} {component.unit}"
            )
        return cleaned


class DamageApplyForm(BootstrapMixin, forms.ModelForm):
    related_outbound = forms.ModelChoiceField(
        label="关联使用申请（申请唯一标识 ID）",
        queryset=OutboundApply.objects.none(),
        required=True,
        empty_label="请选择已通过的使用申请",
        help_text="报损的元件与数量将由该使用申请自动带出",
    )

    class Meta:
        model = DamageApply
        # 移除 component 和 quantity 字段
        fields = ("related_outbound", "reason")
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["related_outbound"].queryset = (
            OutboundApply.objects
            .filter(status=ApplyStatus.APPROVED)
            .select_related("component")
            .order_by("-created_at")
        )

    def clean(self):
        cleaned = super().clean()
        outbound = cleaned.get("related_outbound")
        if outbound:
            # 校验库存是否足够扣减
            component = outbound.component
            if component.stock_quantity < outbound.quantity:
                raise forms.ValidationError(
                    f"当前元件库存（{component.stock_quantity}）不足，"
                    f"无法报损该使用申请的 {outbound.quantity} {component.unit}"
                )
        return cleaned