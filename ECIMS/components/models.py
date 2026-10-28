from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid

User = get_user_model()


class Category(models.Model):
    """品类：支持多级分类，如 电阻 -> 贴片电阻 -> 0603"""
    name = models.CharField("品类名称", max_length=100)
    code = models.CharField("品类编码", max_length=50, unique=True, blank=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="上级品类",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="children",
    )
    description = models.TextField("描述", blank=True)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "品类"
        verbose_name_plural = "品类"
        ordering = ["code", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"],
                name="unique_category_name_per_parent",
            )
        ]

    def __str__(self):
        return f"{self.parent} / {self.name}" if self.parent else self.name

    @property
    def full_path(self):
        """返回完整路径，如 电阻/贴片电阻/0603"""
        names = [self.name]
        node = self.parent
        while node:
            names.append(node.name)
            node = node.parent
        return "/".join(reversed(names))
    
    def save(self, *args, **kwargs):
        # 1. 自动生成 code（未填写时）
        if not self.code:
            self.code = self._generate_code()

        # 2. 防止自己成为自己的上级（简单自环校验）
        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValueError("上级品类不能是自身")

        # 3. 规范化 name：去首尾空格
        if self.name:
            self.name = self.name.strip()

        # 4. 交给 Django 真正写库（INSERT 或 UPDATE）
        super().save(*args, **kwargs)

    def _generate_code(self):
        """基于完整路径生成唯一编码，如 RES-SMD-0603"""
        # 用 full_path 保证多级分类下编码可读且相对唯一
        raw = self.full_path
        # 简单转拼音/英文不现实，这里用 name 的哈希后缀兜底唯一性
        suffix = uuid.uuid4().hex[:6].upper()
        # 清理非法字符（保留字母数字和连字符）
        cleaned = "".join(
            ch if ch.isalnum() or ch in "-_" else "-" for ch in raw
        ).strip("-")
        return f"{cleaned}-{suffix}" if cleaned else suffix    


class Component(models.Model):
    """元件：核心实体"""

    class MountType(models.TextChoices):
        SMD = "SMD", "贴片"
        THT = "THT", "插件"
        OTHER = "OTHER", "其他"

    # 基本信息
    name = models.CharField("元件名称", max_length=200)
    model_number = models.CharField("型号/料号", max_length=100, db_index=True)
    category = models.ForeignKey(
        Category,
        verbose_name="所属品类",
        on_delete=models.PROTECT,
        related_name="components",
    )
    manufacturer = models.CharField("制造商", max_length=100, blank=True)
    description = models.TextField("描述", blank=True)

    # 规格参数
    package = models.CharField("封装", max_length=50, blank=True, db_index=True)
    mount_type = models.CharField(
        "安装方式", max_length=10, choices=MountType.choices, default=MountType.SMD
    )
    value = models.CharField(
        "参数值", max_length=100, blank=True,
        help_text="如 10kΩ、100nF、STM32F103C8T6",
    )
    tolerance = models.CharField("精度/容差", max_length=50, blank=True)
    voltage_rating = models.CharField("额定电压", max_length=50, blank=True)
    power_rating = models.CharField("额定功率", max_length=50, blank=True)
    extra_specs = models.JSONField(
        "扩展参数", default=dict, blank=True,
        help_text="存放灵活参数，如 {'温度系数': '±100ppm'}"
    )

    # 库存相关（冗余字段，便于快速查询，实际以 StockRecord 为准）
    stock_quantity = models.IntegerField(
        "当前库存", default=0, validators=[MinValueValidator(0)]
    )
    safety_stock = models.IntegerField(
        "安全库存", default=0, validators=[MinValueValidator(0)]
    )
    unit = models.CharField("单位", max_length=20, default="个")

    # 位置与批次
    storage_location = models.CharField(
        "存放位置", max_length=100, blank=True,
        help_text="如 A柜-3层-05格"
    )
    batch_number = models.CharField("批次号", max_length=100, blank=True)

    # 采购相关
    cost_price = models.DecimalField(
        "成本单价", max_digits=12, decimal_places=4,
        default=Decimal("0.0000"),
        help_text="采购成本价，用于与参考单价比较、计算毛利",
    )
    reference_price = models.DecimalField(
        "参考单价", max_digits=12, decimal_places=4,
        default=Decimal("0.0000"),
    )
    supplier = models.CharField("供应商", max_length=100, blank=True)

    # 附件与状态
    datasheet = models.FileField(
        "数据手册", upload_to="datasheets/%Y/%m/", null=True, blank=True
    )
    image = models.ImageField(
        "图片", upload_to="components/%Y/%m/", null=True, blank=True
    )
    is_active = models.BooleanField("启用", default=True)

    # 审计
    created_by = models.ForeignKey(
        User, verbose_name="创建人", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="created_components",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "元件"
        verbose_name_plural = "元件"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["model_number"]),
            models.Index(fields=["package"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["model_number", "manufacturer"],
                name="unique_component_model_manufacturer",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.model_number})"

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.safety_stock


class StockRecord(models.Model):
    """出入库流水：所有库存变动的唯一真实来源"""

    class RecordType(models.TextChoices):
        IN = "IN", "入库"
        OUT = "OUT", "出库"
        ADJUST = "ADJUST", "盘点调整"
        RETURN = "RETURN", "退料"

    component = models.ForeignKey(
        Component,
        verbose_name="元件",
        on_delete=models.CASCADE,
        related_name="stock_records",
    )
    record_type = models.CharField(
        "类型", max_length=10, choices=RecordType.choices
    )
    quantity = models.IntegerField(
        "数量", help_text="入库为正，出库为负"
    )
    quantity_after = models.IntegerField("变动后库存")
    unit_price = models.DecimalField(
        "单价", max_digits=12, decimal_places=4,
        default=Decimal("0.0000"),
    )
    batch_number = models.CharField("批次号", max_length=100, blank=True)
    storage_location = models.CharField("存放位置", max_length=100, blank=True)

    # 关联来源（申请单、采购单等，用字符串避免循环导入）
    source_type = models.CharField("来源类型", max_length=50, blank=True)
    source_id = models.PositiveIntegerField("来源ID", null=True, blank=True)

    remark = models.TextField("备注", blank=True)
    operator = models.ForeignKey(
        User, verbose_name="操作人", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="stock_records",
    )
    created_at = models.DateTimeField("操作时间", auto_now_add=True)

    class Meta:
        verbose_name = "出入库流水"
        verbose_name_plural = "出入库流水"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["component", "-created_at"]),
            models.Index(fields=["record_type"]),
            models.Index(fields=["source_type", "source_id"]),
        ]

    def __str__(self):
        sign = "+" if self.quantity >= 0 else ""
        return f"{self.component} {sign}{self.quantity}"