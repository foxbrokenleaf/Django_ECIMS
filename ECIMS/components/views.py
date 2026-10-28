# Create your views here.
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ComponentForm, StockAdjustForm
from .models import Category, Component, StockRecord

PAGE_SIZE = 20


@login_required
def category_list(request):
    qs = Category.objects.select_related("parent").filter(is_active=True)
    keyword = request.GET.get("q")
    if keyword:
        qs = qs.filter(name__icontains=keyword)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "components/category_list.html", {
        "categories": page_obj,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
    })


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


# ---------------------------------------------------------------- 元件管理


def _category_subtree_ids(category_id):
    """返回品类自身及所有下级品类的 ID，用于列表按品类筛选。"""
    children_map = {}
    for pk, parent_id in Category.objects.values_list("id", "parent_id"):
        children_map.setdefault(parent_id, []).append(pk)

    ids, stack = [], [category_id]
    while stack:
        current = stack.pop()
        ids.append(current)
        stack.extend(children_map.get(current, []))
    return ids


@login_required
def component_list(request):
    qs = Component.objects.select_related(
        "category", "category__parent", "category__parent__parent",
    ).filter(is_active=True)

    keyword = (request.GET.get("q") or "").strip()
    if keyword:
        qs = qs.filter(
            Q(name__icontains=keyword)
            | Q(model_number__icontains=keyword)
            | Q(value__icontains=keyword)
            | Q(manufacturer__icontains=keyword)
            | Q(package__icontains=keyword)
        )

    category_id = (request.GET.get("category") or "").strip()
    if category_id.isdigit():
        qs = qs.filter(category_id__in=_category_subtree_ids(int(category_id)))

    mount_type = (request.GET.get("mount_type") or "").strip()
    if mount_type:
        qs = qs.filter(mount_type=mount_type)

    low_stock = request.GET.get("low_stock") == "1"
    if low_stock:
        qs = qs.filter(stock_quantity__lte=F("safety_stock"))

    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, "components/component_list.html", {
        "components": page_obj,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
        "total_count": page_obj.paginator.count,
        "low_stock_count": qs.filter(stock_quantity__lte=F("safety_stock")).count(),
        "categories": Category.objects.filter(is_active=True),
        "mount_types": Component.MountType.choices,
        "filters": {
            "q": keyword,
            "category": category_id,
            "mount_type": mount_type,
            "low_stock": low_stock,
        },
    })


@login_required
def component_detail(request, pk):
    component = get_object_or_404(
        Component.objects.select_related("category", "created_by"), pk=pk
    )
    return render(request, "components/component_detail.html", {
        "component": component,
        "records": component.stock_records.select_related("operator")[:20],
        "stock_form": StockAdjustForm(component=component),
    })


@login_required
def component_create(request):
    if request.method == "POST":
        form = ComponentForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                component = form.save(commit=False)
                component.created_by = request.user
                component.save()

                initial_stock = form.cleaned_data.get("initial_stock") or 0
                if initial_stock:
                    StockRecord.objects.create(
                        component=component,
                        record_type=StockRecord.RecordType.IN,
                        quantity=initial_stock,
                        quantity_after=initial_stock,
                        unit_price=component.reference_price,
                        batch_number=component.batch_number,
                        storage_location=component.storage_location,
                        remark="新增元件初始入库",
                        operator=request.user,
                    )
                    component.stock_quantity = initial_stock
                    component.save(update_fields=["stock_quantity", "updated_at"])

            messages.success(request, f"元件「{component.name}」创建成功")
            return redirect("components:component_detail", pk=component.pk)
    else:
        form = ComponentForm()

    return render(request, "components/component_form.html", {
        "form": form,
        "action": "create",
    })


@login_required
def component_edit(request, pk):
    component = get_object_or_404(Component, pk=pk)
    if request.method == "POST":
        form = ComponentForm(request.POST, request.FILES, instance=component)
        if form.is_valid():
            form.save()
            messages.success(request, f"元件「{component.name}」已更新")
            return redirect("components:component_detail", pk=component.pk)
    else:
        form = ComponentForm(instance=component)

    return render(request, "components/component_form.html", {
        "form": form,
        "component": component,
        "action": "edit",
    })


@login_required
def component_delete(request, pk):
    component = get_object_or_404(Component, pk=pk)
    if request.method == "POST":
        component.is_active = False
        component.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"元件「{component.name}」已停用，历史流水已保留")
        return redirect("components:component_list")
    return render(request, "components/component_confirm_delete.html", {"component": component})


@login_required
@require_POST
def component_stock(request, pk):
    """登记一笔出入库/盘点流水，并同步更新元件冗余库存字段。"""
    component = get_object_or_404(Component, pk=pk)
    form = StockAdjustForm(request.POST, component=component)

    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("components:component_detail", pk=component.pk)

    with transaction.atomic():
        locked = Component.objects.select_for_update().get(pk=component.pk)
        delta = form.signed_quantity()
        quantity_after = locked.stock_quantity + delta

        if quantity_after < 0:
            messages.error(
                request,
                f"库存不足：当前 {locked.stock_quantity} {locked.unit}，本次变动 {delta}。",
            )
            return redirect("components:component_detail", pk=locked.pk)

        StockRecord.objects.create(
            component=locked,
            record_type=form.cleaned_data["record_type"],
            quantity=delta,
            quantity_after=quantity_after,
            unit_price=form.cleaned_data.get("unit_price") or 0,
            batch_number=form.cleaned_data.get("batch_number", ""),
            storage_location=form.cleaned_data.get("storage_location", ""),
            remark=form.cleaned_data.get("remark", ""),
            operator=request.user,
        )
        locked.stock_quantity = quantity_after
        locked.save(update_fields=["stock_quantity", "updated_at"])

        record_type_label = StockRecord.RecordType(form.cleaned_data["record_type"]).label

    messages.success(
        request,
        f"{record_type_label} {abs(delta)} {locked.unit} 已登记，当前库存 {quantity_after} {locked.unit}。",
    )
    return redirect("components:component_detail", pk=locked.pk)