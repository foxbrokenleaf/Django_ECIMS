"""components 应用视图：全部使用类视图（CBV）。

改造要点：
* 所有视图继承 ``LoginRequiredMixin``，未登录访问会跳转到 admin 登录页；
* 页面渲染交给 ListView / DetailView / CreateView / UpdateView / DeleteView /
  FormView 等通用类视图，内部统一通过 ``render()`` / ``TemplateResponse``
  输出，不再手工构造 HttpResponse；
* 表单提交成功后统一使用 ``redirect()`` 跳转（POST-Redirect-GET），
  结果页由独立的类视图渲染，避免刷新页面重复提交。
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    UpdateView,
    View,
)

from .forms import (
    CategoryForm,
    ComponentForm,
    StockAdjustForm,
    StockInApplyForm,
    UsageApplyForm,
)
from .models import Category, Component, StockRecord

PAGE_SIZE = 20

# 申请 Cookie 保留 7 天，仅存最近一次申请单号
APPLY_COOKIE_MAX_AGE = 60 * 60 * 24 * 7


class SafePaginationMixin:
    """分页参数越界（或非法）时回退到最后一页，而不是直接返回 404。"""

    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(
            queryset,
            page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page = (
            self.kwargs.get(self.page_kwarg)
            or self.request.GET.get(self.page_kwarg)
            or 1
        )
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            page_number = paginator.num_pages
        self.page = paginator.get_page(page_number)
        return (
            paginator,
            self.page,
            self.page.object_list,
            self.page.has_other_pages(),
        )


# ---------------------------------------------------------------- 品类管理


class CategoryListView(SafePaginationMixin, LoginRequiredMixin, ListView):
    """品类列表：名称搜索 + 分页。"""

    model = Category
    template_name = "components/category_list.html"
    context_object_name = "categories"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        queryset = Category.objects.select_related("parent").filter(is_active=True)
        keyword = self.request.GET.get("q")
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)
        return queryset


class CategoryDetailView(LoginRequiredMixin, DetailView):
    """品类详情：展示子品类与最近 20 个元件。"""

    model = Category
    template_name = "components/category_detail.html"
    context_object_name = "category"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["children"] = self.object.children.filter(is_active=True)
        context["components"] = self.object.components.filter(is_active=True)[:20]
        return context


class CategoryCreateView(LoginRequiredMixin, CreateView):
    """新增品类：表单校验通过后 redirect() 回列表页。"""

    model = Category
    form_class = CategoryForm
    template_name = "components/category_form.html"
    success_url = reverse_lazy("components:category_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "create"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"品类「{self.object.name}」创建成功")
        return response


class CategoryUpdateView(LoginRequiredMixin, UpdateView):
    """编辑品类：上级品类下拉会自动排除自己。"""

    model = Category
    form_class = CategoryForm
    template_name = "components/category_form.html"
    context_object_name = "category"
    success_url = reverse_lazy("components:category_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "edit"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "更新成功")
        return response


class CategoryDeleteView(LoginRequiredMixin, DeleteView):
    """品类「删除」实际为停用（软删除），历史数据保留。"""

    model = Category
    template_name = "components/category_confirm_delete.html"
    context_object_name = "category"
    success_url = reverse_lazy("components:category_list")

    def form_valid(self, form):
        category = self.object
        category.is_active = False
        category.save(update_fields=["is_active"])
        messages.success(self.request, "已停用")
        return redirect(self.success_url)


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


class ComponentListView(SafePaginationMixin, LoginRequiredMixin, ListView):
    """元件列表：关键字、品类（含子品类）、安装方式、低库存筛选。"""

    model = Component
    template_name = "components/component_list.html"
    context_object_name = "components"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        queryset = Component.objects.select_related(
            "category", "category__parent", "category__parent__parent",
        ).filter(is_active=True)

        keyword = (self.request.GET.get("q") or "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(name__icontains=keyword)
                | Q(model_number__icontains=keyword)
                | Q(value__icontains=keyword)
                | Q(manufacturer__icontains=keyword)
                | Q(package__icontains=keyword)
            )

        category_id = (self.request.GET.get("category") or "").strip()
        if category_id.isdigit():
            queryset = queryset.filter(
                category_id__in=_category_subtree_ids(int(category_id))
            )

        mount_type = (self.request.GET.get("mount_type") or "").strip()
        if mount_type:
            queryset = queryset.filter(mount_type=mount_type)

        low_stock = self.request.GET.get("low_stock") == "1"
        if low_stock:
            queryset = queryset.filter(stock_quantity__lte=F("safety_stock"))

        self.filters = {
            "q": keyword,
            "category": category_id,
            "mount_type": mount_type,
            "low_stock": low_stock,
        }
        self.filtered_queryset = queryset
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.filtered_queryset
        context.update({
            "total_count": queryset.count(),
            "low_stock_count": queryset.filter(
                stock_quantity__lte=F("safety_stock")
            ).count(),
            "categories": Category.objects.filter(is_active=True),
            "mount_types": Component.MountType.choices,
            "filters": self.filters,
        })
        return context


class ComponentDetailView(LoginRequiredMixin, DetailView):
    """元件详情：规格参数 + 出入库流水 + 登记表单。"""

    model = Component
    template_name = "components/component_detail.html"
    context_object_name = "component"
    queryset = Component.objects.select_related("category", "created_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["records"] = self.object.stock_records.select_related("operator")[:20]
        context["stock_form"] = StockAdjustForm(component=self.object)
        return context


class ComponentCreateView(LoginRequiredMixin, CreateView):
    """新增元件：保存元件与初始入库流水后 redirect() 到详情页。"""

    model = Component
    form_class = ComponentForm
    template_name = "components/component_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "create"
        return context

    def form_valid(self, form):
        with transaction.atomic():
            self.object = form.save(commit=False)
            self.object.created_by = self.request.user
            self.object.save()

            initial_stock = form.cleaned_data.get("initial_stock") or 0
            if initial_stock:
                StockRecord.objects.create(
                    component=self.object,
                    record_type=StockRecord.RecordType.IN,
                    quantity=initial_stock,
                    quantity_after=initial_stock,
                    unit_price=self.object.reference_price,
                    batch_number=self.object.batch_number,
                    storage_location=self.object.storage_location,
                    remark="新增元件初始入库",
                    operator=self.request.user,
                )
                self.object.stock_quantity = initial_stock
                self.object.save(update_fields=["stock_quantity", "updated_at"])

        messages.success(self.request, f"元件「{self.object.name}」创建成功")
        return redirect("components:component_detail", pk=self.object.pk)


class ComponentUpdateView(LoginRequiredMixin, UpdateView):
    """编辑元件：库存数量只能通过出入库流水变更。"""

    model = Component
    form_class = ComponentForm
    template_name = "components/component_form.html"
    context_object_name = "component"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action"] = "edit"
        return context

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f"元件「{self.object.name}」已更新")
        return redirect("components:component_detail", pk=self.object.pk)


class ComponentDeleteView(LoginRequiredMixin, DeleteView):
    """元件「删除」实际为停用（软删除），历史流水保留。"""

    model = Component
    template_name = "components/component_confirm_delete.html"
    context_object_name = "component"
    success_url = reverse_lazy("components:component_list")

    def form_valid(self, form):
        component = self.object
        component.is_active = False
        component.save(update_fields=["is_active", "updated_at"])
        messages.success(
            self.request, f"元件「{component.name}」已停用，历史流水已保留"
        )
        return redirect(self.success_url)


class ComponentStockView(LoginRequiredMixin, View):
    """登记一笔出入库/盘点流水，并同步更新元件冗余库存字段。

    只接受 POST（http_method_names 限制），GET 访问返回 405。
    """

    http_method_names = ["post"]

    def post(self, request, pk):
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
                    f"库存不足：当前 {locked.stock_quantity} {locked.unit}，"
                    f"本次变动 {delta}。",
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

            record_type_label = StockRecord.RecordType(
                form.cleaned_data["record_type"]
            ).label

        messages.success(
            request,
            f"{record_type_label} {abs(delta)} {locked.unit} 已登记，"
            f"当前库存 {quantity_after} {locked.unit}。",
        )
        return redirect("components:component_detail", pk=locked.pk)


# ---------------------------------------------------------------- 入库申请 / 使用申请
#
#   * 任务一：从 request 上读取请求方法、路径、完整路径、查询参数与客户端 IP；
#   * 任务二：表单提交成功后使用 redirect() 跳转到结果页（POST-Redirect-GET），
#            结果页由 ApplyResultView 通过 render() 渲染，不再手工构造响应。


class InsufficientStockError(Exception):
    """使用申请时库存不足，无法生成出库流水。"""


def _client_ip(request):
    """从 request.META 中取客户端 IP，兼容反向代理写入的 X-Forwarded-For。"""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _request_snapshot(request):
    """任务一：把 HttpRequest 中的关键信息整理成模板可直接渲染的字典。"""
    return {
        # 获取请求信息
        "method": request.method,
        "path": request.path,
        "full_path": request.get_full_path(),
        "scheme": request.scheme,
        "is_secure": request.is_secure(),
        # 获取客户端信息（request.META）
        "client_ip": _client_ip(request),
        "host": request.META.get("HTTP_HOST", ""),
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
        # 获取请求参数（request.GET）
        "query_string": request.META.get("QUERY_STRING", ""),
        "query_params": [(key, request.GET.getlist(key)) for key in request.GET],
        # 其他辅助信息
        "cookie_count": len(request.COOKIES),
        "user": request.user.get_username() if request.user.is_authenticated else "匿名用户",
        "server_time": timezone.now(),
    }


def _initial_from_query(request):
    """任务一：从 URL 查询字符串中读取参数，作为申请表单的初始值。

    支持的参数：component / quantity / batch_number / storage_location / remark
    例如：/components/applications/stock-in/?component=3&quantity=50
    """
    initial = {}

    component_id = (request.GET.get("component") or "").strip()
    if component_id.isdigit():
        initial["component"] = component_id

    quantity = (request.GET.get("quantity") or "").strip()
    if quantity.isdigit() and int(quantity) > 0:
        initial["quantity"] = int(quantity)

    for param in ("batch_number", "storage_location", "remark"):
        value = (request.GET.get(param) or "").strip()
        if value:
            initial[param] = value

    return initial


def _component_from_value(value):
    """把查询参数或表单里的元件主键转换成 Component 实例。"""
    if value in (None, ""):
        return None
    try:
        pk = int(value)
    except (TypeError, ValueError):
        return None
    return Component.objects.select_related("category").filter(pk=pk).first()


APPLY_CONFIG = {
    "in": {
        "mode": "in",
        "page_title": "入库申请",
        "page_icon": "bi-arrow-down-circle",
        "page_subtitle": "提交采购、退料等入库申请，保存后立即写入入库流水并同步库存",
        "form_class": StockInApplyForm,
        "record_type": StockRecord.RecordType.IN,
        "source_type": StockRecord.SourceType.STOCK_IN_APPLY,
        "apply_prefix": "RK",
        "cookie_name": "ecims_last_stock_in_apply",
        "sign": 1,
    },
    "use": {
        "mode": "use",
        "page_title": "使用申请",
        "page_icon": "bi-arrow-up-circle",
        "page_subtitle": "提交元件领用申请，保存后立即生成出库流水并校验库存",
        "form_class": UsageApplyForm,
        "record_type": StockRecord.RecordType.OUT,
        "source_type": StockRecord.SourceType.USAGE_APPLY,
        "apply_prefix": "SY",
        "cookie_name": "ecims_last_usage_apply",
        "sign": -1,
    },
}


def _save_application(request, form, config):
    """把申请写入 StockRecord，并同步更新元件的冗余库存字段。"""
    data = form.cleaned_data
    component = data["component"]
    quantity = data["quantity"]
    delta = quantity * config["sign"]

    unit_price = data.get("unit_price")
    if unit_price is None:
        unit_price = (
            component.reference_price
            if config["mode"] == "in"
            else Decimal("0.0000")
        )

    with transaction.atomic():
        locked = Component.objects.select_for_update().get(pk=component.pk)
        quantity_after = locked.stock_quantity + delta
        if quantity_after < 0:
            raise InsufficientStockError(
                f"库存不足：{locked.name} 当前库存 {locked.stock_quantity} "
                f"{locked.unit}，本次申请 {quantity} {locked.unit}。"
            )

        record = StockRecord.objects.create(
            component=locked,
            record_type=config["record_type"],
            quantity=delta,
            quantity_after=quantity_after,
            unit_price=unit_price,
            batch_number=data.get("batch_number") or locked.batch_number,
            storage_location=data.get("storage_location") or locked.storage_location,
            source_type=config["source_type"],
            apply_no=StockRecord.next_apply_no(config["apply_prefix"]),
            applicant=request.user,
            remark=(data.get("remark") or "").strip(),
            operator=request.user,
        )
        locked.stock_quantity = quantity_after
        locked.save(update_fields=["stock_quantity", "updated_at"])

    return record


class ApplicationFormView(LoginRequiredMixin, FormView):
    """入库申请 / 使用申请的公共类视图。

    GET：读取 request.GET 预填表单，返回申请页面；
    POST：校验通过后写入流水，并通过 redirect() 跳转到结果页。
    """

    template_name = "components/apply_form.html"
    config = None

    def get_config(self):
        if self.config is None:
            raise ImproperlyConfigured("ApplicationFormView 子类必须设置 config")
        return self.config

    def get_initial(self):
        initial = super().get_initial()
        initial.update(_initial_from_query(self.request))

        component = _component_from_value(initial.get("component"))
        if component is not None and self.get_config()["mode"] == "in":
            # 查询参数带入元件时，顺带预填入库单价、批次与存放位置
            initial.setdefault("unit_price", component.reference_price)
            initial.setdefault("batch_number", component.batch_number)
            initial.setdefault("storage_location", component.storage_location)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = self.get_config()
        form = context["form"]

        raw_component = (
            form.data.get("component") if form.is_bound
            else self.request.GET.get("component")
        )
        context.update({
            "mode": config["mode"],
            "page_title": config["page_title"],
            "page_icon": config["page_icon"],
            "page_subtitle": config["page_subtitle"],
            "request_info": _request_snapshot(self.request),
            "selected_component": _component_from_value(raw_component),
            "apply_cookie_name": config["cookie_name"],
            "last_apply_no": self.request.COOKIES.get(config["cookie_name"], ""),
        })
        return context

    def form_valid(self, form):
        try:
            record = _save_application(self.request, form, self.get_config())
        except InsufficientStockError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)

        # POST 成功后 redirect() 到结果页，由 ApplyResultView 负责渲染
        response = redirect("components:apply_result", pk=record.pk)
        response.set_cookie(
            self.get_config()["cookie_name"],
            record.apply_no,
            max_age=APPLY_COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="Lax",
        )
        return response


class StockInApplyView(ApplicationFormView):
    """入库申请：读取 request 信息，提交后 redirect() 到结果页。"""

    form_class = StockInApplyForm
    config = APPLY_CONFIG["in"]


class UsageApplyView(ApplicationFormView):
    """使用申请：读取 request 信息，提交后 redirect() 到结果页。"""

    form_class = UsageApplyForm
    config = APPLY_CONFIG["use"]


class ApplyResultView(LoginRequiredMixin, DetailView):
    """申请受理回执：由 render() 渲染，展示申请单与本次请求信息。"""

    model = StockRecord
    template_name = "components/apply_result.html"
    context_object_name = "record"

    def get_queryset(self):
        return StockRecord.objects.select_related(
            "component", "component__category", "applicant", "operator",
        ).filter(source_type__in=(
            StockRecord.SourceType.STOCK_IN_APPLY,
            StockRecord.SourceType.USAGE_APPLY,
        ))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        record = self.object
        mode = (
            "in"
            if record.source_type == StockRecord.SourceType.STOCK_IN_APPLY
            else "use"
        )
        config = APPLY_CONFIG[mode]
        context.update({
            "component": record.component,
            "mode": config["mode"],
            "page_title": config["page_title"],
            "page_icon": config["page_icon"],
            "request_info": _request_snapshot(self.request),
            "apply_cookie_name": config["cookie_name"],
            "last_apply_no": self.request.COOKIES.get(config["cookie_name"], ""),
            "response_status": 200,
        })
        return context
