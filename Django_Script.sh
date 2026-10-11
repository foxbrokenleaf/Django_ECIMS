from django.urls import reverse, resolve

# ============================================
# 1. 应用命名空间：反向解析
# ============================================
print(reverse("components:category_list"))
# 期望：/components/categories/

print(reverse("components:category_detail", args=[1]))
# 期望：/components/categories/1/

# ============================================
# 2. 实例命名空间：反向解析
# ============================================
print(reverse("test:category_list"))
# 期望：/demo/components/categories/

# ============================================
# 3. 带参数的反向解析：args 与 kwargs
# ============================================
print(reverse("components:category_detail", args=[1]))
# 期望：/components/categories/1/

print(reverse("components:category_detail", kwargs={"pk": 1}))
# 期望：/components/categories/1/

# ============================================
# 4. 正向解析：查看命名空间
# ============================================
match = resolve("/components/categories/")
print("namespace  :", match.namespace)
# 期望：components

print("app_name   :", match.app_name)
# 期望：components

print("url_name   :", match.url_name)
# 期望：category_list

print("view_name  :", match.view_name)
# 期望：components:category_list

# ============================================
# 5. 实例命名空间验证：解析 demo 路径
# ============================================
match2 = resolve("/demo/components/categories/")
print("namespace  :", match2.namespace)
# 期望：test

print("app_name   :", match2.app_name)
# 期望：components

print("view_name  :", match2.view_name)
# 期望：test:category_list