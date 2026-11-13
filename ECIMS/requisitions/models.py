from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction


class ApplyStatus(models.TextChoices):
    PENDING  = "pending",  "待审批"
    APPROVED = "approved", "已通过"
    REJECTED = "rejected", "已驳回"
    CANCELED = "canceled", "已取消"


APPLY_NO_PREFIX = {
    "inbound":  "IN",
    "outbound": "OUT",
    "damage":   "DMG",
}


class BaseApply(models.Model):
    """申请单公共字段，抽象基类。"""
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="+", verbose_name="申请人",
    )
    # 入库申请允许不选库内元件，改为自定义名称
    component = models.ForeignKey(
        "components.Component", on_delete=models.PROTECT,
        related_name="+", verbose_name="元件",
        null=True, blank=True,
    )
    quantity = models.PositiveIntegerField("数量")
    status = models.CharField(
        "状态", max_length=16, choices=ApplyStatus.choices,
        default=ApplyStatus.PENDING,
    )

    # 业务唯一编号，如 IN-20261113-0001
    apply_no = models.CharField(
        "申请编号", max_length=32, unique=True,
        editable=False, blank=True, db_index=True,
    )

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+", verbose_name="审批人",
    )
    review_note = models.TextField("审批备注", blank=True)
    created_at  = models.DateTimeField("申请时间", auto_now_add=True)
    reviewed_at = models.DateTimeField("审批时间", null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    # 子类必须覆盖，返回 'inbound' / 'outbound' / 'damage'
    apply_kind = None

    def __str__(self):
        """美化下拉框及后台的展示字符串，如：OUT-20261113-0001 - 贴片电阻"""
        if self.component_id:
            comp_name = self.component.name
        else:
            comp_name = getattr(self, "custom_name", "") or "未知元件"
            
        # 如果有编号，带上编号显示
        prefix = f"{self.apply_no} - " if self.apply_no else ""
        return f"{prefix}{comp_name} ({self.quantity})"

    def _generate_apply_no(self):
        prefix = APPLY_NO_PREFIX.get(self.apply_kind, "APP")
        # 注意：USE_TZ=False 时不能用 timezone.localdate()，用标准库 date.today()
        today = date.today().strftime("%Y%m%d")
        base = f"{prefix}-{today}-"

        model = type(self)
        last = (
            model.objects
            .filter(apply_no__startswith=base)
            .order_by("-apply_no")
            .values_list("apply_no", flat=True)
            .first()
        )
        if last:
            try:
                seq = int(last.rsplit("-", 1)[1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f"{base}{seq:04d}"

    def save(self, *args, **kwargs):
        if self.apply_no:
            return super().save(*args, **kwargs)

        # 并发兜底：重试若干次，unique=True 保证不重号
        for _ in range(5):
            self.apply_no = self._generate_apply_no()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.apply_no = ""
        raise IntegrityError("生成申请编号失败，请重试")


class InboundApply(BaseApply):
    apply_kind = "inbound"

    reason = models.TextField("申请理由", blank=True)
    custom_name  = models.CharField("自定义元件名称", max_length=200, blank=True)
    custom_model = models.CharField("自定义型号/料号", max_length=100, blank=True)

    class Meta(BaseApply.Meta):
        verbose_name = verbose_name_plural = "入库申请"

    def clean(self):
        super().clean()
        custom_name = (self.custom_name or "").strip()
        if not self.component_id and not custom_name:
            raise ValidationError("请选择库内元件，或填写自定义元件名称")
        if self.component_id and custom_name:
            raise ValidationError("库内元件与自定义名称只能二选一")

    def save(self, *args, **kwargs):
        if self.component_id:
            self.custom_name = ""
            self.custom_model = ""
        else:
            self.custom_name = (self.custom_name or "").strip()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        if self.component_id:
            return f"{self.component.name} ({self.component.model_number})"
        return f"{self.custom_name} ({self.custom_model or '自定义'})"


class OutboundApply(BaseApply):
    apply_kind = "outbound"

    purpose = models.TextField("用途说明", blank=True)

    class Meta(BaseApply.Meta):
        verbose_name = verbose_name_plural = "使用申请"

    def clean(self):
        super().clean()
        if not self.component_id:
            raise ValidationError("请选择元件")


class DamageApply(BaseApply):
    apply_kind = "damage"

    reason = models.TextField("报损原因")

    # 关联的使用申请：报损的"申请唯一标识 ID"引用它
    related_outbound = models.ForeignKey(
        "requisitions.OutboundApply",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="damage_applies",
        verbose_name="关联使用申请",
    )

    class Meta(BaseApply.Meta):
        verbose_name = verbose_name_plural = "报损申请"

    def clean(self):
        super().clean()
        
        # 1. 如果既没选关联申请，又没选元件，报错
        if not self.related_outbound_id and not self.component_id:
            raise ValidationError("请选择关联使用申请或选择元件")
            
        # 2. 如果有关联申请，校验一致性
        if self.related_outbound_id:
            # 从关联申请里读取元件来对比，因为当前 self.component_id 可能还是空的
            target_component_id = self.related_outbound.component_id
            
            # 如果表单里选了元件，但和关联申请的元件不一致
            if self.component_id and self.component_id != target_component_id:
                raise ValidationError("关联的使用申请元件与报损元件不一致")
                
            if self.related_outbound.status != ApplyStatus.APPROVED:
                raise ValidationError("只能关联已通过的使用申请")
                
            # 如果填了数量，校验数量是否超过原申请
            if self.quantity and self.quantity > self.related_outbound.quantity:
                raise ValidationError("报损数量不能超过该使用申请的出库数量")

    def save(self, *args, **kwargs):
        # 自动从关联的使用申请中继承元件和数量
        if self.related_outbound_id:
            self.component = self.related_outbound.component
            self.quantity = self.related_outbound.quantity
        super().save(*args, **kwargs)

    @property
    def display_apply_no(self):
        """报损单展示用的标识：优先显示关联使用申请的编号。"""
        if self.related_outbound_id:
            return self.related_outbound.apply_no
        return self.apply_no