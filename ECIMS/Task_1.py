from components.models import Category

print("=" * 60)
print("开始 CRUD 练习")
print("=" * 60)

# ---------- 0. 清理旧数据（保证可重复运行） ----------
print("\n[0] 清理旧测试数据")
Category.objects.filter(name__in=["电阻", "贴片电阻", "0603", "电容"]).delete()
print("清理完成，当前记录数：", Category.objects.count())

# ==========================================================
# 1. CREATE 增
# ==========================================================
print("\n" + "=" * 60)
print("[1] CREATE：创建数据")
print("=" * 60)

# 方式一：实例化 + save()
print("\n-- 方式一：实例化 + save() --")
cat = Category(name="电阻")
print("save 前 pk:", cat.pk, "| code:", repr(cat.code))
cat.save()
print("save 后 pk:", cat.pk, "| code:", repr(cat.code), "| full_path:", cat.full_path)

# 方式二：objects.create()
print("\n-- 方式二：objects.create() --")
smd = Category.objects.create(name="贴片电阻", parent=cat)
print("create 后 pk:", smd.pk, "| code:", repr(smd.code), "| full_path:", smd.full_path)

# 三级品类
c0603 = Category.objects.create(name="0603", parent=smd)
print("create 后 pk:", c0603.pk, "| full_path:", c0603.full_path)

# 另一个根品类
cap = Category.objects.create(name="电容")
print("create 后 pk:", cap.pk, "| full_path:", cap.full_path)

# ==========================================================
# 2. READ 查
# ==========================================================
print("\n" + "=" * 60)
print("[2] READ：查询数据")
print("=" * 60)

print("\n-- all() 全部 --")
for c in Category.objects.all():
    print(f"  pk={c.pk} code={c.code!r} path={c.full_path}")

print("\n-- get() 单条 --")
one = Category.objects.get(pk=cat.pk)
print(f"  get(pk={cat.pk}) -> {one.full_path}")

print("\n-- filter() 条件查询 --")
print("  filter(parent__isnull=True) 根品类：")
for c in Category.objects.filter(parent__isnull=True):
    print(f"    {c.full_path}")

print("  filter(name__contains='电阻') 名称含'电阻'：")
for c in Category.objects.filter(name__contains="电阻"):
    print(f"    {c.full_path}")

print("  filter(parent=cat) 电阻的直接子类：")
for c in Category.objects.filter(parent=cat):
    print(f"    {c.full_path}")

# ==========================================================
# 3. UPDATE 改
# ==========================================================
print("\n" + "=" * 60)
print("[3] UPDATE：修改数据")
print("=" * 60)

# 方式一：改属性 + save()
print("\n-- 方式一：改属性 + save() --")
print("改前：", smd.name, "|", smd.full_path)
smd.name = "SMD电阻"
smd.save()
smd.refresh_from_db()
print("改后：", smd.name, "|", smd.full_path)

# 方式二：查询集 update() 批量更新
print("\n-- 方式二：filter().update() 批量更新 --")
count = Category.objects.filter(parent=cat).update(is_active=False)
print(f"  将 parent={cat.pk} 的子类全部设为 is_active=False，影响 {count} 条")
for c in Category.objects.filter(parent=cat):
    print(f"    {c.full_path} | is_active={c.is_active}")

# ==========================================================
# 4. DELETE 删
# ==========================================================
print("\n" + "=" * 60)
print("[4] DELETE：删除数据")
print("=" * 60)

# 方式一：单个实例 delete()
print("\n-- 方式一：实例 delete() --")
print("删除前 0603：", c0603.full_path)
c0603.delete()
print("删除后 0603 是否还存在：", Category.objects.filter(pk=c0603.pk).exists())

# 方式二：查询集 delete() 批量删除
print("\n-- 方式二：查询集 delete() --")
qs = Category.objects.filter(name="电容")
print("待删除电容数量：", qs.count())
qs.delete()
print("删除后电容数量：", Category.objects.filter(name="电容").count())

# ---------- 最终状态 ----------
print("\n" + "=" * 60)
print("[5] 最终数据库状态")
print("=" * 60)
for c in Category.objects.all():
    print(f"  pk={c.pk} code={c.code!r} path={c.full_path} is_active={c.is_active}")
print("\nCRUD 练习结束")