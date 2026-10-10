from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Category


@login_required
def category_list(request):
    qs = Category.objects.select_related("parent").filter(is_active=True)
    keyword = request.GET.get("q")
    if keyword:
        qs = qs.filter(name__icontains=keyword)
    return render(request, "components/category_list.html", {"categories": qs})


@login_required
def category_detail(request, pk):
    category = get_object_or_404(Category, pk=pk)
    return render(request, "components/category_detail.html", {
        "category": category,
        "children": category.children.filter(is_active=True),
        "components": category.components.filter(is_active=True)[:20],
    })


@login_required
def category_create(request):
    if request.method == "POST":
        name = request.POST.get("name")
        code = request.POST.get("code")
        parent_id = request.POST.get("parent") or None
        description = request.POST.get("description", "")
        if not name:
            messages.error(request, "品类名称不能为空")
        else:
            Category.objects.create(
                name=name, code=code or "",
                parent_id=parent_id, description=description,
            )
            messages.success(request, f"品类「{name}」创建成功")
            return redirect("components:category_list")
    return render(request, "components/category_form.html", {
        "parents": Category.objects.filter(is_active=True),
        "action": "create",
    })


@login_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        category.name = request.POST.get("name", category.name)
        category.code = request.POST.get("code", category.code)
        category.description = request.POST.get("description", category.description)
        parent_id = request.POST.get("parent") or None
        if parent_id and int(parent_id) != category.pk:
            category.parent_id = parent_id
        elif not parent_id:
            category.parent_id = None
        category.save()
        messages.success(request, "更新成功")
        return redirect("components:category_list")
    return render(request, "components/category_form.html", {
        "category": category,
        "parents": Category.objects.exclude(pk=pk).filter(is_active=True),
        "action": "edit",
    })


@login_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        category.is_active = False
        category.save(update_fields=["is_active"])
        messages.success(request, "已停用")
        return redirect("components:category_list")
    return render(request, "components/category_confirm_delete.html", {"category": category})