from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from components.models import Category, Component, StockRecord
from .forms import DamageApplyForm, InboundApplyForm, OutboundApplyForm
from .models import ApplyStatus, DamageApply, InboundApply, OutboundApply

PAGE_SIZE = 20

MODEL_MAP = {
    "inbound":  InboundApply,
    "outbound": OutboundApply,
    "damage":   DamageApply,
}
TEMPLATE_MAP = {
    "inbound":  "requisitions/inbound_list.html",
    "outbound": "requisitions/outbound_list.html",
    "damage":   "requisitions/damage_list.html",
}
TITLE_MAP = {
    "inbound":  "入库申请",
    "outbound": "使用申请",
    "damage":   "报损申请",
}
FORM_MAP = {
    "inbound":  InboundApplyForm,
    "outbound": OutboundApplyForm,
    "damage":   DamageApplyForm,
}


def _is_approver(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def _display_no(apply_obj):
    """报损单优先展示关联使用申请编号，其余用自身编号。"""
    return getattr(apply_obj, "display_apply_no", apply_obj.apply_no)


def _apply_common(request, kind):
    """三种申请的公共列表 + 新建逻辑。"""
    model = MODEL_MAP[kind]

    if request.method == "POST":
        form = FORM_MAP[kind](request.POST)
        if form.is_valid():
            apply_obj = form.save(commit=False)
            apply_obj.applicant = request.user
            
            # ★ 针对报损申请：自动从关联使用申请里继承元件和数量
            if kind == "damage" and apply_obj.related_outbound_id:
                apply_obj.component = apply_obj.related_outbound.component
                apply_obj.quantity = apply_obj.related_outbound.quantity
                
            apply_obj.full_clean()
            apply_obj.save()
            messages.success(
                request,
                f"{TITLE_MAP[kind]} {_display_no(apply_obj)} 已提交，等待审批",
            )
            return redirect(f"requisitions:{kind}")
        messages.error(request, "请检查表单填写")
    else:
        form = FORM_MAP[kind]()

    qs = model.objects.select_related("applicant", "component", "reviewer")
    if kind == "damage":
        qs = qs.select_related("related_outbound")
    if not _is_approver(request.user):
        qs = qs.filter(applicant=request.user)

    status = request.GET.get("status")
    if status in ApplyStatus.values:
        qs = qs.filter(status=status)

    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, TEMPLATE_MAP[kind], {
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
        "total_count": page_obj.paginator.count,
        "statuses": ApplyStatus.choices,
        "current_status": status,
        "kind": kind,
        "title": TITLE_MAP[kind],
        "form": form,
        "is_approver": _is_approver(request.user),
    })


@login_required
def inbound(request):
    return _apply_common(request, "inbound")


@login_required
def outbound(request):
    return _apply_common(request, "outbound")


@login_required
def damage(request):
    return _apply_common(request, "damage")


@login_required
@require_POST
def cancel_apply(request, kind, pk):
    """申请人取消自己待审批的申请。"""
    model = MODEL_MAP.get(kind)
    if model is None:
        messages.error(request, "未知申请类型")
        return redirect("components:component_list")

    apply_obj = get_object_or_404(model, pk=pk)
    if apply_obj.applicant_id != request.user.pk:
        raise PermissionDenied("只能取消自己的申请")
    if apply_obj.status != ApplyStatus.PENDING:
        messages.warning(request, "该申请已处理，无法取消")
        return redirect(f"requisitions:{kind}")

    apply_obj.status = ApplyStatus.CANCELED
    apply_obj.save(update_fields=["status"])
    messages.success(request, f"{_display_no(apply_obj)} 已取消")
    return redirect(f"requisitions:{kind}")


@login_required
@require_POST
def review_apply(request, kind, pk):
    """审批通过 / 驳回。通过时同步变更库存并落 StockRecord。"""
    if not _is_approver(request.user):
        raise PermissionDenied("无权审批")

    model = MODEL_MAP.get(kind)
    if model is None:
        messages.error(request, "未知申请类型")
        return redirect("components:component_list")

    qs = model.objects.select_related("component")
    if kind == "damage":
        qs = qs.select_related("related_outbound")
    apply_obj = get_object_or_404(qs, pk=pk)
    if apply_obj.status != ApplyStatus.PENDING:
        messages.warning(request, "该申请已处理，不能重复审批")
        return redirect(f"requisitions:{kind}")

    action = request.POST.get("action")  # approve / reject
    note = request.POST.get("review_note", "").strip()

    with transaction.atomic():
        # 入库申请且未选库内元件：审批通过时先自动建档，再入库
        if kind == "inbound" and not apply_obj.component_id and action == "approve":
            default_category = (
                Category.objects.filter(code="TEMP", is_active=True).first()
                or Category.objects.filter(is_active=True).first()
            )
            if default_category is None:
                messages.error(
                    request,
                    "系统中没有可用品类，无法自动建档，请先在品类管理中创建",
                )
                return redirect(f"requisitions:{kind}")

            model_number = (apply_obj.custom_model or apply_obj.custom_name)[:100]
            component, _created = Component.objects.get_or_create(
                model_number=model_number,
                manufacturer="",
                defaults={
                    "name": apply_obj.custom_name[:200],
                    "category": default_category,
                    "stock_quantity": 0,
                    "is_active": True,
                    "created_by": request.user,
                },
            )
            apply_obj.component = component
            apply_obj.save(update_fields=["component"])

        locked = Component.objects.select_for_update().get(pk=apply_obj.component_id)

        if action == "approve":
            if kind == "inbound":
                delta = apply_obj.quantity
                record_type = StockRecord.RecordType.IN
            elif kind == "outbound":
                delta = -apply_obj.quantity
                record_type = StockRecord.RecordType.OUT
            else:  # damage
                delta = -apply_obj.quantity
                record_type = StockRecord.RecordType.ADJUST

            quantity_after = locked.stock_quantity + delta
            if quantity_after < 0:
                messages.error(
                    request,
                    f"库存不足：当前 {locked.stock_quantity} {locked.unit}，"
                    f"本次需要 {-delta} {locked.unit}",
                )
                return redirect(f"requisitions:{kind}")

            StockRecord.objects.create(
                component=locked,
                record_type=record_type,
                quantity=delta,
                quantity_after=quantity_after,
                unit_price=locked.reference_price,
                batch_number=locked.batch_number,
                storage_location=locked.storage_location,
                source_type=f"{kind}_apply",
                source_id=apply_obj.pk,
                remark=f"{TITLE_MAP[kind]} {_display_no(apply_obj)} 审批通过"
                       + (f"：{note}" if note else ""),
                operator=request.user,
            )
            locked.stock_quantity = quantity_after
            locked.save(update_fields=["stock_quantity", "updated_at"])
            apply_obj.status = ApplyStatus.APPROVED
        elif action == "reject":
            apply_obj.status = ApplyStatus.REJECTED
        else:
            messages.error(request, "无效操作")
            return redirect(f"requisitions:{kind}")

        apply_obj.reviewer = request.user
        apply_obj.review_note = note
        apply_obj.reviewed_at = timezone.now()
        apply_obj.save(update_fields=[
            "status", "reviewer", "review_note", "reviewed_at",
        ])

    messages.success(request, f"{_display_no(apply_obj)} 审批完成")
    return redirect(f"requisitions:{kind}")