"""labels 应用模型：标签模板配置与打印记录。

- ``LabelTemplate``：描述一张标签的物理尺寸、版面布局、纸张间隔、
  显示哪些元件属性、二维码内容以及默认打印份数，供页面选择并由
  ``services`` 组装打印数据。
- ``LabelPrintRecord``：每次提交打印后按元件落一条记录，便于追溯谁在
  什么时候、用什么模板、哪台打印机打印了多少份。
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class LabelTemplate(models.Model):
    """标签模板：控制标签尺寸与打印字段。"""

    class QrContent(models.TextChoices):
        UID = "uid", "唯一标识符 UID（可扫码查询）"
        MODEL = "model", "型号/料号"
        NAME_MODEL = "name_model", "元件名称 + 型号"

    class GapType(models.TextChoices):
        UNSET = "unset", "随打印机设置"
        NONE = "none", "连续纸（无间隔）"
        GAP = "gap", "间隙纸"
        BLACK = "black", "黑标纸"

    class QrPosition(models.TextChoices):
        BOTTOM_RIGHT = "bottom_right", "右下角"
        BOTTOM_LEFT = "bottom_left", "左下角"
        TOP_RIGHT = "top_right", "右上角"
        TOP_LEFT = "top_left", "左上角"

    name = models.CharField("模板名称", max_length=100, unique=True)
    description = models.TextField("模板说明", blank=True)

    width_mm = models.DecimalField(
        "标签宽度(mm)", max_digits=6, decimal_places=1, default=Decimal("40.0"),
        validators=[MinValueValidator(Decimal("10.0")), MaxValueValidator(Decimal("300.0"))],
    )
    height_mm = models.DecimalField(
        "标签高度(mm)", max_digits=6, decimal_places=1, default=Decimal("30.0"),
        validators=[MinValueValidator(Decimal("10.0")), MaxValueValidator(Decimal("300.0"))],
    )
    font_name = models.CharField(
        "打印字体", max_length=50, default="黑体",
        help_text="需为打印机所在电脑已安装的字体，如 黑体、宋体、微软雅黑",
    )

    # 版面布局：预览与真实打印共用这些参数
    margin_mm = models.DecimalField(
        "内容边距(mm)", max_digits=4, decimal_places=1, default=Decimal("1.8"),
        validators=[MinValueValidator(Decimal("0.0")), MaxValueValidator(Decimal("20.0"))],
        help_text="文字与二维码距离标签边缘的留白，单位毫米",
    )
    line_spacing_mm = models.DecimalField(
        "行间距(mm)", max_digits=4, decimal_places=1, default=Decimal("0.5"),
        validators=[MinValueValidator(Decimal("0.0")), MaxValueValidator(Decimal("10.0"))],
        help_text="相邻两行内容之间的额外间距，单位毫米",
    )
    font_scale = models.DecimalField(
        "字号缩放", max_digits=3, decimal_places=1, default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("2.0"))],
        help_text="1.0 为默认字号；0.8 缩小，1.2 放大",
    )

    include_qr = models.BooleanField("打印二维码", default=True)
    qr_content = models.CharField(
        "二维码内容", max_length=20, choices=QrContent.choices, default=QrContent.UID,
        help_text="选择 UID 时，用手机扫码后可在“扫码查询”页面定位元件",
    )
    qr_size_mm = models.DecimalField(
        "二维码尺寸(mm)", max_digits=5, decimal_places=1, default=Decimal("0.0"),
        validators=[MinValueValidator(Decimal("0.0")), MaxValueValidator(Decimal("100.0"))],
        help_text="0 表示按标签尺寸自动计算；设置后按指定边长绘制",
    )
    qr_position = models.CharField(
        "二维码位置", max_length=20, choices=QrPosition.choices,
        default=QrPosition.BOTTOM_RIGHT,
    )

    # 纸张参数：标签间隔用于让打印机按正确节距走纸
    gap_type = models.CharField(
        "纸张类型", max_length=10, choices=GapType.choices, default=GapType.UNSET,
        help_text="间隙纸请选择“间隙纸”；不确定时保持“随打印机设置”",
    )
    gap_mm = models.DecimalField(
        "标签间隔(mm)", max_digits=4, decimal_places=1, default=Decimal("0.0"),
        validators=[MinValueValidator(Decimal("0.0")), MaxValueValidator(Decimal("20.0"))],
        help_text="两张标签之间的距离；0 表示使用打印机已校准的间隔",
    )

    # 各字段是否打印到标签上（元件名称、型号始终打印）
    show_value = models.BooleanField("显示参数值", default=True)
    show_package = models.BooleanField("显示封装/安装方式", default=True)
    show_stock = models.BooleanField("显示库存数量", default=True)
    show_location = models.BooleanField("显示存放位置", default=True)
    show_batch = models.BooleanField("显示批次号", default=True)
    show_manufacturer = models.BooleanField("显示制造商", default=False)
    show_category = models.BooleanField("显示品类", default=False)

    default_copies = models.PositiveSmallIntegerField(
        "默认打印份数", default=1,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    is_default = models.BooleanField("默认模板", default=False)
    is_active = models.BooleanField("启用", default=True)

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "标签模板"
        verbose_name_plural = "标签模板"
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="unique_default_label_template",
            )
        ]

    def __str__(self):
        return f"{self.name}（{self.width_mm}×{self.height_mm}mm）"

    def save(self, *args, **kwargs):
        # 先取消其它默认模板，避免触发 unique_default_label_template 约束
        if self.is_default:
            others = type(self).objects.filter(is_default=True)
            if self.pk:
                others = others.exclude(pk=self.pk)
            others.update(is_default=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_default(cls):
        """返回当前默认模板；没有设置默认时退回第一个启用中的模板。"""
        template = (
            cls.objects.filter(is_active=True)
            .order_by("-is_default", "name")
            .first()
        )
        return template




class LabelPrintRecord(models.Model):
    """标签打印记录：每个元件每次提交打印记一条。"""

    class Status(models.TextChoices):
        SUCCESS = "success", "打印成功"
        FAILED = "failed", "打印失败"

    batch_id = models.UUIDField("批次ID", default=uuid.uuid4, db_index=True, editable=False)
    component = models.ForeignKey(
        "components.Component",
        verbose_name="元件",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="label_prints",
    )
    # 冗余快照：元件被删除后记录仍可追溯
    component_name = models.CharField("元件名称", max_length=200, blank=True)
    component_model = models.CharField("型号/料号", max_length=100, blank=True)
    component_uid = models.UUIDField("元件UID", null=True, blank=True)

    template = models.ForeignKey(
        LabelTemplate,
        verbose_name="标签模板",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="print_records",
    )
    template_name = models.CharField("模板名称", max_length=100, blank=True)

    copies = models.PositiveIntegerField("每个元件份数", default=1)
    printer_name = models.CharField("打印机", max_length=200, blank=True)
    status = models.CharField(
        "打印状态", max_length=10, choices=Status.choices, default=Status.SUCCESS,
    )
    message = models.TextField("结果信息", blank=True)

    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="操作人",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="label_print_records",
    )
    created_at = models.DateTimeField("打印时间", auto_now_add=True)

    class Meta:
        verbose_name = "标签打印记录"
        verbose_name_plural = "标签打印记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["component", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return (
            f"{self.component_name or '未知元件'} × {self.copies}"
            f"（{self.get_status_display()}）"
        )

