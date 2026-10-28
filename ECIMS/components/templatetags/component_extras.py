"""components 应用的模板标签库。

模板中使用前先加载：{% load component_extras %}
"""

from django import template
from django.http import QueryDict
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def stock_badge(component, with_unit=True):
    """渲染库存徽章；库存小于等于安全库存时显示红色预警。

    用法：
        {% stock_badge component %}
        {% stock_badge component False %}   不带单位
    """
    quantity = f"{component.stock_quantity} {component.unit}" if with_unit else component.stock_quantity

    if component.is_low_stock:
        return format_html(
            '<span class="badge bg-danger-subtle text-danger border border-danger-subtle"'
            ' title="安全库存 {}">'
            '<i class="bi bi-exclamation-triangle me-1"></i>{}</span>',
            component.safety_stock,
            quantity,
        )
    return format_html(
        '<span class="badge bg-success-subtle text-success border border-success-subtle">'
        "{}</span>",
        quantity,
    )


@register.simple_tag
def record_type_badge(record):
    """渲染出入库类型徽章：入库绿、出库红、盘点黄、退料蓝。

    用法：{% record_type_badge stock_record %}
    """
    styles = {
        "IN": ("success", "success"),
        "OUT": ("danger", "danger"),
        "ADJUST": ("warning", "warning-emphasis"),
        "RETURN": ("info", "info-emphasis"),
    }
    background, text = styles.get(record.record_type, ("secondary", "secondary"))
    return format_html(
        '<span class="badge bg-{}-subtle text-{} border border-{}-subtle">{}</span>',
        background, text, background, record.get_record_type_display(),
    )


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    """在当前 GET 参数基础上生成查询串，常用于分页链接保留筛选条件。

    - 覆盖已有参数：{% querystring page=page_obj.next_page_number %}
    - 传 None 移除参数：{% querystring page=None q=None %}
    """
    request = context.get("request")
    params = request.GET.copy() if request is not None else QueryDict(mutable=True)

    for key, value in kwargs.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = value

    return mark_safe(params.urlencode())


@register.simple_tag(takes_context=True)
def nav_active(context, *view_names):
    """当前请求命中指定视图名时返回 active，用于导航高亮。

    支持前缀匹配，因此 {% nav_active 'components:category' %} 可以同时命中
    category_list / category_detail / category_create / category_edit / category_delete。
    """
    match = getattr(context.get("request"), "resolver_match", None)
    current = getattr(match, "view_name", "") or ""

    for name in view_names:
        if current == name or current.startswith(f"{name}_"):
            return "active"
    return ""
