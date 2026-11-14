"""labels 应用视图：从库存选择元件、预览并打印标签。

流程说明：

1. ``home`` 展示可打印的库存元件，支持关键词/品类/安装方式/库存筛选；
2. 勾选元件后 ``label_print`` 统一调用 ``services.print_labels``，
   每个元件写入一条 ``LabelPrintRecord``；
3. ``label_preview`` 用与真实打印完全相同的版面数据做页面预览；
4. ``scan_component`` 供手机扫标签二维码后按 UID 定位元件；
5. ``export_components`` / ``export_history`` 按当前筛选条件导出 Excel，
   支持 ``?layout=dual`` 导出单工作表双联表。
"""

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from components.models import Category, Component

from .exports import (
    build_component_workbook,
    build_print_record_workbook,
    export_filename,
    xlsx_response,
)
from .forms import LabelPrintSettingsForm, LabelTemplateForm
from .models import LabelPrintRecord, LabelTemplate
from .services import (
    MAX_LABELS,
    build_label_layout,
    list_printers,
    print_labels,
)

PAGE_SIZE = 20


def _category_subtree_ids(category_id):
    """返回品类及其所有子孙品类 ID，与 components 筛选行为保持一致。"""
    children_map = {}
    for pk, parent_id in Category.objects.values_list("pk", "parent_id"):
        children_map.setdefault(parent_id, []).append(pk)

    ids, stack = [], [category_id]
    while stack:
        current = stack.pop()
        ids.append(current)
        stack.extend(children_map.get(current, []))
    return ids


def _filter_components(request):
    """按 GET 参数筛选可打印元件，返回（queryset, 筛选条件）。"""
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
            | Q(storage_location__icontains=keyword)
            | Q(batch_number__icontains=keyword)
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

    has_stock = request.GET.get("has_stock") == "1"
    if has_stock:
        qs = qs.filter(stock_quantity__gt=0)

    return qs, {
        "q": keyword,
        "category": category_id,
        "mount_type": mount_type,
        "low_stock": low_stock,
        "has_stock": has_stock,
    }


def _filter_print_records(request):
    """按 GET 参数筛选打印记录，返回（queryset, 筛选条件）。

    普通用户只能看到自己的记录，管理员可查看全部；列表页与 Excel 导出
    共用同一套筛选逻辑，保证导出的数据与页面显示一致。
    """
    qs = LabelPrintRecord.objects.select_related("component", "template", "operator")
    if not request.user.is_staff:
        qs = qs.filter(operator=request.user)

    keyword = (request.GET.get("q") or "").strip()
    if keyword:
        qs = qs.filter(
            Q(component_name__icontains=keyword)
            | Q(component_model__icontains=keyword)
            | Q(printer_name__icontains=keyword)
            | Q(template_name__icontains=keyword)
        )

    status = (request.GET.get("status") or "").strip()
    if status in LabelPrintRecord.Status.values:
        qs = qs.filter(status=status)

    return qs, {"q": keyword, "status": status}


@login_required
def home(request):
    """标签打印主页：筛选库存元件、选择模板/打印机。"""
    qs, filters = _filter_components(request)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))

    printer_info = list_printers()
    templates = LabelTemplate.objects.filter(is_active=True)
    default_template = LabelTemplate.get_default()
    form = LabelPrintSettingsForm(
        printers=printer_info["printers"],
        initial={
            "template": default_template,
            "copies": default_template.default_copies if default_template else 1,
            "printer": printer_info["default_printer"],
        },
    )

    return render(request, "labels/home.html", {
        "components": page_obj,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
        "total_count": page_obj.paginator.count,
        "low_stock_count": qs.filter(stock_quantity__lte=F("safety_stock")).count(),
        "categories": Category.objects.filter(is_active=True),
        "mount_types": Component.MountType.choices,
        "filters": filters,
        "templates": templates,
        "default_template": default_template,
        "form": form,
        "printer_info": printer_info,
        "max_labels": MAX_LABELS,
    })


def _is_dual_export(request):
    """导出版式参数：``layout=dual`` 时输出双联表，默认输出单联表。"""
    return (request.GET.get("layout") or "").strip() == "dual"


@login_required
def export_components(request):
    """按当前筛选条件导出元件标签清单为 Excel（不受分页限制）。

    通过 ``?layout=dual`` 可导出双联表：同一工作表左右各一联，
    每行并排放置两个元件（奇数条时右联留空）。
    """
    qs, _ = _filter_components(request)
    dual = _is_dual_export(request)
    workbook = build_component_workbook(qs, dual=dual)
    prefix = "元件标签清单-双联" if dual else "元件标签清单"
    return xlsx_response(workbook, export_filename(prefix))


@login_required
@require_POST
def label_print(request):
    """提交打印：校验元件/模板/打印机后调用 dtpweb，并落打印记录。"""
    component_ids = [
        int(value) for value in request.POST.getlist("component") if value.isdigit()
    ]
    if not component_ids:
        messages.error(request, "请先勾选需要打印标签的元件。")
        return redirect("labels:home")

    order = {pk: index for index, pk in enumerate(component_ids)}
    components = sorted(
        Component.objects.filter(pk__in=component_ids, is_active=True).select_related("category"),
        key=lambda component: order.get(component.pk, 0),
    )
    if not components:
        messages.error(request, "所选元件不存在或已停用，请刷新页面后重试。")
        return redirect("labels:home")

    printer_info = list_printers()
    if not printer_info["service_available"]:
        messages.error(request, printer_info["error"] or "打印服务不可用。")
        return redirect("labels:home")
    if not printer_info["printers"]:
        messages.error(request, "未检测到可用打印机，请检查打印机连接与驱动。")
        return redirect("labels:home")

    form = LabelPrintSettingsForm(request.POST, printers=printer_info["printers"])
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("labels:home")

    template = form.cleaned_data["template"]
    copies = form.cleaned_data["copies"]
    printer_key = form.cleaned_data.get("printer") or ""

    label_count = len(components) * copies
    if label_count > MAX_LABELS:
        messages.error(
            request,
            f"单次最多打印 {MAX_LABELS} 张标签，当前选择为 {label_count} 张，请减少元件或份数。",
        )
        return redirect("labels:home")

    result = print_labels(
        components, template, copies=copies, printer_key=printer_key,
    )
    status = (
        LabelPrintRecord.Status.SUCCESS if result["ok"]
        else LabelPrintRecord.Status.FAILED
    )
    printer_name = result.get("printer_name") or printer_info["default_printer_name"]
    batch_id = uuid.uuid4()
    LabelPrintRecord.objects.bulk_create([
        LabelPrintRecord(
            batch_id=batch_id,
            component=component,
            component_name=component.name,
            component_model=component.model_number,
            component_uid=component.uid,
            template=template,
            template_name=template.name,
            copies=copies,
            printer_name=printer_name,
            status=status,
            message=result["message"],
            operator=request.user,
        )
        for component in components
    ])

    if result["ok"]:
        messages.success(request, result["message"])
    else:
        messages.error(request, f"打印失败：{result['message']}")
    return redirect("labels:home")


@login_required
def printer_status(request):
    """打印机检测接口：页面加载/手动刷新时调用。"""
    return JsonResponse(list_printers())


@login_required
def label_preview(request, pk):
    """单个元件的标签预览，版面数据与真实打印一致。"""
    component = get_object_or_404(
        Component.objects.select_related("category", "category__parent"), pk=pk,
    )
    printer_info = list_printers()

    template_id = (request.GET.get("template") or "").strip()
    template = None
    if template_id.isdigit():
        template = LabelTemplate.objects.filter(pk=template_id, is_active=True).first()
    if template is None:
        template = LabelTemplate.get_default()

    layout = build_label_layout(component, template) if template else None
    form = LabelPrintSettingsForm(
        printers=printer_info["printers"],
        initial={
            "template": template,
            "copies": template.default_copies if template else 1,
            "printer": printer_info["default_printer"],
        },
    )

    return render(request, "labels/preview.html", {
        "component": component,
        "template": template,
        "templates": LabelTemplate.objects.filter(is_active=True),
        "layout": layout,
        "form": form,
        "printer_info": printer_info,
    })


@login_required
def label_history(request):
    """打印历史：普通用户只看自己的记录，管理员可查看全部。"""
    qs, filters = _filter_print_records(request)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "labels/history.html", {
        "records": page_obj,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
        "total_count": page_obj.paginator.count,
        "filters": filters,
        "status_choices": LabelPrintRecord.Status.choices,
    })


@login_required
def export_history(request):
    """按当前筛选条件导出打印记录为 Excel（普通用户仅导出本人记录）。

    通过 ``?layout=dual`` 可导出双联表：同一工作表左右各一联。
    """
    qs, _ = _filter_print_records(request)
    dual = _is_dual_export(request)
    workbook = build_print_record_workbook(qs, dual=dual)
    prefix = "标签打印记录-双联" if dual else "标签打印记录"
    return xlsx_response(workbook, export_filename(prefix))


@login_required
def template_list(request):
    """标签模板列表。"""
    return render(request, "labels/template_list.html", {
        "templates": LabelTemplate.objects.all(),
    })


@login_required
def template_create(request):
    """新增标签模板：仅超级用户。"""
    if not request.user.is_superuser:
        raise PermissionDenied("只有超级用户可以新增标签模板。")

    if request.method == "POST":
        form = LabelTemplateForm(request.POST)
        if form.is_valid():
            template = form.save()
            messages.success(request, f"标签模板「{template.name}」创建成功。")
            return redirect("labels:template_list")
    else:
        form = LabelTemplateForm()

    return render(request, "labels/template_form.html", {
        "form": form,
        "action": "create",
    })


@login_required
def template_edit(request, pk):
    """编辑标签模板：仅超级用户。"""
    if not request.user.is_superuser:
        raise PermissionDenied("只有超级用户可以修改标签模板。")

    template = get_object_or_404(LabelTemplate, pk=pk)
    if request.method == "POST":
        form = LabelTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, f"标签模板「{template.name}」已更新。")
            return redirect("labels:template_list")
    else:
        form = LabelTemplateForm(instance=template)

    return render(request, "labels/template_form.html", {
        "form": form,
        "template": template,
        "action": "edit",
    })


@login_required
@require_POST
def template_toggle(request, pk):
    """启用/停用模板：仅超级用户。"""
    if not request.user.is_superuser:
        raise PermissionDenied("只有超级用户可以启用或停用标签模板。")

    template = get_object_or_404(LabelTemplate, pk=pk)
    template.is_active = not template.is_active
    if not template.is_active:
        template.is_default = False
    template.save(update_fields=["is_active", "is_default", "updated_at"])
    state = "启用" if template.is_active else "停用"
    messages.success(request, f"标签模板「{template.name}」已{state}。")
    return redirect("labels:template_list")


@login_required
def scan_component(request, uid):
    """扫码查询：标签二维码内容为元件 UID 时跳转到此页。"""
    component = get_object_or_404(
        Component.objects.select_related("category", "category__parent"), uid=uid,
    )
    return render(request, "labels/scan.html", {"component": component})



