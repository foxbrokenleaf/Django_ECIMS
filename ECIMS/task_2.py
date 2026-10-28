# -*- coding: utf-8 -*-
"""
任务二：F对象与Q对象的使用
基于 components.Component 模型
运行方式（推荐）：
    python manage.py shell
    >>> exec(open('task2_fq.py', encoding='utf-8').read())
"""

from decimal import Decimal

from django.db.models import F, Q

from components.models import Component, Category

print("=" * 60)
print("任务二：F对象与Q对象的使用")
print("=" * 60)

# ==========================================================
# 0. 准备：清理旧测试数据，造几条样本
# ==========================================================
print("\n[0] 准备测试数据")

# 清理本脚本造的测试元件（按型号前缀识别，避免误删真实数据）
Component.objects.filter(model_number__startswith="TEST-").delete()

# 找一个品类挂靠（没有就建一个）
cat, _ = Category.objects.get_or_create(
    code="TEST-CAT", defaults={"name": "测试品类"}
)

# 造 4 条样本，覆盖不同场景
samples = [
    # name, model, package, mount, cost, ref, stock, safety, mfr
    ("测试电阻A", "TEST-R-001", "0603", "SMD", "0.0500", "0.0800", 100, 20, "厂商A"),
    ("测试电阻B", "TEST-R-002", "0805", "SMD", "0.1000", "0.0900", 10, 20, "厂商B"),   # 参考价 < 成本价，库存低
    ("测试电容C", "TEST-C-001", "0603", "SMD", "0.2000", "0.3000", 50, 10, "厂商A"),
    ("测试连接器D", "TEST-J-001", "THT", "THT", "1.0000", "1.5000", 5, 10, "厂商C"),   # 插件
]

for name, model, pkg, mount, cost, ref, stock, safety, mfr in samples:
    Component.objects.create(
        name=name,
        model_number=model,
        category=cat,
        package=pkg,
        mount_type=mount,
        cost_price=Decimal(cost),
        reference_price=Decimal(ref),
        stock_quantity=stock,
        safety_stock=safety,
        manufacturer=mfr,
    )

print("样本数量：", Component.objects.filter(model_number__startswith="TEST-").count())

# ==========================================================
# 1. F 对象
# ==========================================================
print("\n" + "=" * 60)
print("[1] F对象演示")
print("=" * 60)

# 1.1 字段间比较：参考价 > 成本价
print("\n-- 1.1 参考价 > 成本价（字段间比较）--")
qs = Component.objects.filter(
    model_number__startswith="TEST-",
    reference_price__gt=F("cost_price"),
)
for c in qs:
    print(f"  {c.name}: cost={c.cost_price} ref={c.reference_price}")

# 1.2 库存 <= 安全库存
print("\n-- 1.2 库存 <= 安全库存 --")
qs = Component.objects.filter(
    model_number__startswith="TEST-",
    stock_quantity__lte=F("safety_stock"),
)
for c in qs:
    print(f"  {c.name}: stock={c.stock_quantity} safety={c.safety_stock}")

# 1.3 批量更新：参考价 +10
print("\n-- 1.3 批量更新：所有测试元件参考价 +10 --")
print("更新前：")
for c in Component.objects.filter(model_number__startswith="TEST-"):
    print(f"  {c.name}: ref={c.reference_price}")

Component.objects.filter(
    model_number__startswith="TEST-"
).update(reference_price=F("reference_price") + 10)

print("更新后（refresh_from_db 确认）：")
for c in Component.objects.filter(model_number__startswith="TEST-"):
    c.refresh_from_db()
    print(f"  {c.name}: ref={c.reference_price}")

# ==========================================================
# 2. Q 对象
# ==========================================================
print("\n" + "=" * 60)
print("[2] Q对象演示")
print("=" * 60)

BASE = Q(model_number__startswith="TEST-")   # 只作用于测试数据

# 2.1 或：贴片 或 插件
print("\n-- 2.1 或：贴片 或 插件 --")
qs = Component.objects.filter(
    BASE & (Q(mount_type="SMD") | Q(mount_type="THT"))
)
for c in qs:
    print(f"  {c.name}: mount={c.mount_type}")

# 2.2 非：排除厂商A
print("\n-- 2.2 非：排除厂商A --")
qs = Component.objects.filter(BASE & ~Q(manufacturer="厂商A"))
for c in qs:
    print(f"  {c.name}: mfr={c.manufacturer}")

# 2.3 与：贴片 且 0603 且 启用
print("\n-- 2.3 与：贴片 且 封装0603 且 启用 --")
qs = Component.objects.filter(
    BASE
    & Q(mount_type="SMD")
    & Q(package__startswith="0603")
    & Q(is_active=True)
)
for c in qs:
    print(f"  {c.name}: pkg={c.package} mount={c.mount_type} active={c.is_active}")

# 2.4 组合复用多个 Q 对象
print("\n-- 2.4 组合复用： (贴片 或 插件) 且 启用 --")
q_smd = Q(mount_type="SMD")
q_tht = Q(mount_type="THT")
q_active = Q(is_active=True)

qs = Component.objects.filter(BASE & (q_smd | q_tht) & q_active)
for c in qs:
    print(f"  {c.name}: mount={c.mount_type} active={c.is_active}")

print("\n-- 2.5 非(贴片 或 插件) —— 即其他安装方式 --")
qs = Component.objects.filter(BASE & ~(q_smd | q_tht))
for c in qs:
    print(f"  {c.name}: mount={c.mount_type}")

# ==========================================================
# 3. F + Q 结合
# ==========================================================
print("\n" + "=" * 60)
print("[3] F + Q 结合：参考价 > 成本价 且 库存 <= 安全库存")
print("=" * 60)

qs = Component.objects.filter(
    BASE
    & Q(reference_price__gt=F("cost_price"))
    & Q(stock_quantity__lte=F("safety_stock"))
)
for c in qs:
    print(
        f"  {c.name}: cost={c.cost_price} ref={c.reference_price} "
        f"stock={c.stock_quantity} safety={c.safety_stock}"
    )

# ==========================================================
# 4. 验证与清理说明
# ==========================================================
print("\n" + "=" * 60)
print("[4] 最终测试数据状态")
print("=" * 60)

for c in Component.objects.filter(model_number__startswith="TEST-"):
    print(
        f"  pk={c.pk} model={c.model_number} name={c.name} "
        f"cost={c.cost_price} ref={c.reference_price} "
        f"stock={c.stock_quantity} safety={c.safety_stock} "
        f"mount={c.mount_type} active={c.is_active}"
    )

print("\n提示：测试数据以 model_number 前缀 TEST- 标识，可执行以下命令清理：")
print('  Component.objects.filter(model_number__startswith="TEST-").delete()')
print("\n任务二结束")