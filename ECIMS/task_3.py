# -*- coding: utf-8 -*-
"""
任务三：执行原生SQL语句
运行方式：
    python manage.py shell
    >>> exec(open('task_3.py', encoding='utf-8').read())
"""

from decimal import Decimal

from django.db import connection
from django.db.models import F

from components.models import Component, Category

print("=" * 60)
print("任务三：执行原生SQL语句")
print("=" * 60)

# ---------- 0. 准备测试数据 ----------
print("\n[0] 准备测试数据")
Component.objects.filter(model_number__startswith="TEST-").delete()
cat, _ = Category.objects.get_or_create(code="TEST-CAT", defaults={"name": "测试品类"})

samples = [
    ("测试电阻A", "TEST-R-001", "0603", "SMD", "0.0500", "0.0800", 100, 20, "厂商A"),
    ("测试电阻B", "TEST-R-002", "0805", "SMD", "0.1000", "0.0900", 10, 20, "厂商B"),
    ("测试电容C", "TEST-C-001", "0603", "SMD", "0.2000", "0.3000", 50, 10, "厂商A"),
    ("测试连接器D", "TEST-J-001", "THT", "THT", "1.0000", "1.5000", 5, 10, "厂商C"),
]
for name, model, pkg, mount, cost, ref, stock, safety, mfr in samples:
    Component.objects.create(
        name=name, model_number=model, category=cat, package=pkg,
        mount_type=mount, cost_price=Decimal(cost), reference_price=Decimal(ref),
        stock_quantity=stock, safety_stock=safety, manufacturer=mfr,
    )
print("样本数量：", Component.objects.filter(model_number__startswith="TEST-").count())

# ==========================================================
# 1. cursor 执行原生 SELECT
# ==========================================================
print("\n" + "=" * 60)
print("[1] cursor 执行原生 SELECT")
print("=" * 60)

with connection.cursor() as cursor:
    cursor.execute(
        "SELECT id, name, model_number, cost_price, reference_price "
        "FROM components_component WHERE model_number LIKE %s ORDER BY id",
        ["TEST-%"],
    )
    rows = cursor.fetchall()

print("返回类型：", type(rows).__name__, "，行数：", len(rows))
for row in rows:
    print("  ", row)

# 拿列名，转成 dict 更直观
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT id, name, model_number, cost_price FROM components_component "
        "WHERE model_number LIKE %s ORDER BY id LIMIT 2",
        ["TEST-%"],
    )
    cols = [c[0] for c in cursor.description]
    for row in cursor.fetchall():
        print("  dict:", dict(zip(cols, row)))

# ==========================================================
# 2. cursor 执行原生 UPDATE
# ==========================================================
print("\n" + "=" * 60)
print("[2] cursor 执行原生 UPDATE（参考价 +1）")
print("=" * 60)

print("更新前：")
for c in Component.objects.filter(model_number__startswith="TEST-").order_by("id"):
    print(f"  {c.model_number}: ref={c.reference_price}")

with connection.cursor() as cursor:
    affected = cursor.execute(
        "UPDATE components_component SET reference_price = reference_price + 1 "
        "WHERE model_number LIKE %s",
        ["TEST-%"],
    )
print("影响行数：", affected)

print("更新后：")
for c in Component.objects.filter(model_number__startswith="TEST-").order_by("id"):
    c.refresh_from_db()
    print(f"  {c.model_number}: ref={c.reference_price}")

# ==========================================================
# 3. raw() 执行原生 SELECT，返回模型实例
# ==========================================================
print("\n" + "=" * 60)
print("[3] raw() 执行原生 SELECT（返回模型实例）")
print("=" * 60)

qs = Component.objects.raw(
    "SELECT * FROM components_component WHERE model_number LIKE %s ORDER BY id",
    ["TEST-%"],
)
print("返回类型：", type(qs).__name__)
for obj in qs:
    print(
        f"  实例 pk={obj.pk} model={obj.model_number} name={obj.name} "
        f"cost={obj.cost_price} ref={obj.reference_price}"
    )

# 3.2 只查部分字段
print("\n-- 3.2 只查部分字段（其余字段延迟加载）--")
first = Component.objects.filter(model_number__startswith="TEST-").first()
qs = Component.objects.raw(
    "SELECT id, name, model_number FROM components_component WHERE id = %s",
    [first.pk],
)
obj = qs[0]
print("  已查字段 name:", obj.name)
print("  未查字段 cost_price（会触发延迟查询）:", obj.cost_price)

# 3.3 带复杂条件的 raw
print("\n-- 3.3 raw 带字段比较条件 --")
qs = Component.objects.raw(
    "SELECT * FROM components_component "
    "WHERE model_number LIKE %s AND reference_price > cost_price ORDER BY id",
    ["TEST-%"],
)
for obj in qs:
    print(f"  {obj.model_number}: cost={obj.cost_price} ref={obj.reference_price}")

# ==========================================================
# 4. 清理提示
# ==========================================================
print("\n" + "=" * 60)
print("[4] 清理测试数据")
print("=" * 60)
print('执行：Component.objects.filter(model_number__startswith="TEST-").delete()')
print("\n任务三结束")