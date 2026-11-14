"""标签数据组装与 dtpweb 打印服务封装。

本模块把“元件属性 -> 标签版面 -> dtpweb 绘图指令”拆开，方便：

- 页面预览与真实打印共用同一套版面数据（``build_label_layout``）；
- 单元测试不依赖打印机，通过 ``DTPWEB_DRY_RUN`` 或 mock 验证业务逻辑；
- 打印助手未启动、打印机离线等异常统一转换成友好提示。
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# 单次提交的安全上限，避免误操作一次生成过多标签
MAX_COPIES = 100
MAX_LABELS = 500

# 模板中的纸张类型 -> dtpweb LPA_GapType 数值
GAP_TYPE_CODES = {
    "none": 0,    # 连续纸（小票纸）
    "gap": 2,     # 间隙纸
    "black": 3,   # 黑标纸
}


def _to_float(value, default=0.0):
    """把 Decimal/字符串等安全转换为 float，非法值返回默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_gap_print_options(template):
    """把模板的纸张类型与标签间隔转换为 dtpweb 打印参数。

    ``gapLength`` 仅由 dtpweb 的 JSON 批量打印 jobInfo 支持，单位毫米；
    因此调用方看到 ``gapLength`` 时需要使用 JSON 模式提交任务。
    """
    options = {}
    gap_type = getattr(template, "gap_type", "unset")
    if gap_type in GAP_TYPE_CODES:
        options["gapType"] = GAP_TYPE_CODES[gap_type]

    gap_mm = _to_float(getattr(template, "gap_mm", 0), 0.0)
    gap_mm = min(max(gap_mm, 0.0), 20.0)
    if gap_mm > 0:
        options["gapLength"] = round(gap_mm, 2)
    return options


# dtpweb 返回的打印机 type 含义（兼容新旧版本）
PRINTER_TYPE_LABELS = {
    1: "本地",
    2: "局域网",
    3: "WiFi",
    29: "WiFi",
}

SERVICE_UNAVAILABLE_MESSAGE = (
    "未检测到 dtpweb 打印助手或打印机不可用。请确认已安装标签打印机驱动"
    "（Windows 驱动已内置打印助手）并保持打印助手运行后重试。"
)


# ------------------------------------------------------------------ 打印机信息


def _printer_type_label(value):
    """把 dtpweb 的打印机类型转成中文说明。"""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "其他"

    if value in PRINTER_TYPE_LABELS:
        return PRINTER_TYPE_LABELS[value]
    if 1 <= value <= 9:
        return "本地"
    if 11 <= value <= 19:
        return "局域网"
    return "其他"


def _printer_name(printer):
    """兼容不同版本 SDK 的打印机名称字段。"""
    return (
        printer.get("deviceName")
        or printer.get("name")
        or printer.get("printerName")
        or "未命名打印机"
    )


def make_printer_key(printer):
    """生成前端下拉框使用的稳定键值，避免同名打印机冲突。"""
    return f"{printer.get('type', '')}|{_printer_name(printer)}"


def _serialize_printer(printer):
    return {
        "key": make_printer_key(printer),
        "name": _printer_name(printer),
        "type": printer.get("type", ""),
        "type_label": _printer_type_label(printer.get("type")),
        "ip": printer.get("ip", "") or "",
    }


def _dry_run_printer():
    return {
        "key": "dry-run|演示打印机",
        "name": "演示打印机（DTPWEB_DRY_RUN）",
        "type": 0,
        "type_label": "演示",
        "ip": "",
    }


def list_printers():
    """检测打印服务并返回打印机列表。

    返回值结构::

        {
            "service_available": bool,   # dtpweb 打印助手是否可用
            "printers": [{"key", "name", "type", "type_label", "ip"}],
            "default_printer": "key",    # 前端默认选中项
            "default_printer_name": str,
            "error": str,                # 不可用时的提示
        }
    """
    if getattr(settings, "DTPWEB_DRY_RUN", False):
        printer = _dry_run_printer()
        return {
            "service_available": True,
            "printers": [printer],
            "default_printer": printer["key"],
            "default_printer_name": printer["name"],
            "error": "",
        }

    try:
        from dtpweb import DTPWeb  # 延迟导入：无打印环境时不影响其他页面
    except ImportError:
        logger.exception("无法导入 dtpweb 模块")
        return {
            "service_available": False,
            "printers": [],
            "default_printer": "",
            "default_printer_name": "",
            "error": "未安装 dtpweb Python 模块，请执行 pip install dtpweb-*.whl 后重试。",
        }

    try:
        api = DTPWeb(ip=getattr(settings, "DTPWEB_IP", "") or None)
        if not api.check_plugin():
            return {
                "service_available": False,
                "printers": [],
                "default_printer": "",
                "default_printer_name": "",
                "error": SERVICE_UNAVAILABLE_MESSAGE,
            }

        raw_printers = api.get_printers() or []
    except Exception as exc:  # noqa: BLE001 - 网络层异常统一转成页面提示
        logger.exception("检测 dtpweb 打印服务失败")
        return {
            "service_available": False,
            "printers": [],
            "default_printer": "",
            "default_printer_name": "",
            "error": f"检测打印服务失败：{exc}",
        }

    printers = [_serialize_printer(p) for p in raw_printers if isinstance(p, dict)]
    if not printers:
        return {
            "service_available": True,
            "printers": [],
            "default_printer": "",
            "default_printer_name": "",
            "error": "打印助手运行正常，但没有检测到可用打印机，请检查打印机连接与驱动。",
        }

    configured = (getattr(settings, "DTPWEB_DEFAULT_PRINTER", "") or "").strip()
    default_key = ""
    if configured:
        for printer in printers:
            if configured in (printer["name"], printer["key"]):
                default_key = printer["key"]
                break
    if not default_key:
        default_key = printers[0]["key"]

    default_name = next(
        (p["name"] for p in printers if p["key"] == default_key), printers[0]["name"]
    )
    return {
        "service_available": True,
        "printers": printers,
        "default_printer": default_key,
        "default_printer_name": default_name,
        "error": "",
    }


def find_printer(printers, key):
    """按前端传来的 key 查找打印机；找不到时退回第一台。"""
    for printer in printers:
        if make_printer_key(printer) == key:
            return printer
    return printers[0] if printers else None


# ------------------------------------------------------------------ 标签版面


def _text_units(text):
    """粗略估算文本宽度（以字高为 1 个单位）。"""
    return sum(1.0 if ord(char) > 0x2E80 else 0.55 for char in text)


def fit_text(text, max_width_mm, font_height_mm):
    """按标签可用宽度截断文本，超出部分用省略号表示。"""
    text = (text or "").strip()
    if not text:
        return ""

    max_units = max(1.0, max_width_mm / max(font_height_mm, 0.1))
    if _text_units(text) <= max_units:
        return text

    budget = max(0.5, max_units - 1.0)  # 预留省略号
    result, used = [], 0.0
    for char in text:
        char_units = 1.0 if ord(char) > 0x2E80 else 0.55
        if used + char_units > budget:
            break
        result.append(char)
        used += char_units
    return "".join(result).rstrip() + "…"


def get_qr_content(component, template):
    """按模板配置生成二维码文本。"""
    if template.qr_content == template.QrContent.MODEL:
        return component.model_number or str(component.uid)
    if template.qr_content == template.QrContent.NAME_MODEL:
        return f"{component.name} {component.model_number}".strip()
    return str(component.uid)


def build_label_layout(component, template):
    """生成标签版面数据，供页面预览与 dtpweb 绘制共用。

    版面参数全部来自模板，便于用户调整边距、行距、字号与二维码位置。
    返回结构::

        {
            "width": 40.0, "height": 30.0,
            "margin": 1.8, "line_spacing": 0.5, "gap_mm": 0.0,
            "lines": [{"text", "x", "y", "width", "height", "font_height"}],
            "qr": {"content", "x", "y", "size"} | None,
        }
    """
    width = float(template.width_mm)
    height = float(template.height_mm)
    scale = max(0.5, height / 30.0)

    # 边距不能超过标签宽高，避免自定义参数造成负的可用区域
    margin = _to_float(getattr(template, "margin_mm", 1.8), 1.8)
    margin = min(max(margin, 0.0), width / 3.0, height / 3.0)
    line_spacing = _to_float(getattr(template, "line_spacing_mm", 0.5), 0.5)
    line_spacing = min(max(line_spacing, 0.0), 10.0)
    font_scale = _to_float(getattr(template, "font_scale", 1.0), 1.0)
    font_scale = min(max(font_scale, 0.5), 2.0)
    gap_mm = _to_float(getattr(template, "gap_mm", 0.0), 0.0)
    gap_mm = min(max(gap_mm, 0.0), 20.0)

    base_font = max(1.6, height / 13.0) * font_scale
    name_font = base_font * 1.35
    model_font = base_font * 1.1
    body_font = base_font * 0.95

    qr_size = 0.0
    qr_gap = 1.5 * scale
    if template.include_qr:
        qr_setting = _to_float(getattr(template, "qr_size_mm", 0.0), 0.0)
        qr_size = (
            qr_setting if qr_setting > 0
            else min(width * 0.30, height * 0.42, 14.0 * scale)
        )
        # 给文字保留最小宽度，避免二维码设置过大时文字被挤出标签
        min_text_width = max(4.0, width * 0.2)
        qr_limit = width - 2 * margin - qr_gap - min_text_width
        qr_size = min(
            qr_size, max(0.0, qr_limit), height - 2 * margin,
        )
        if qr_size < 1.0:
            qr_size = 0.0
    if not qr_size:
        qr_gap = 0.0

    qr_position = getattr(template, "qr_position", "bottom_right")
    qr_on_left = qr_position in ("bottom_left", "top_left")
    qr_on_top = qr_position in ("top_left", "top_right")

    text_x = margin + (qr_size + qr_gap if qr_on_left else 0.0)
    text_width = width - 2 * margin - (qr_size + qr_gap if qr_size else 0.0)
    text_width = max(0.5, text_width)

    lines = []
    cursor = margin

    def add_line(text, font_height, line_gap=1.25):
        nonlocal cursor
        text = (text or "").strip()
        if not text:
            return
        line_height = font_height * line_gap
        if cursor + line_height > height - margin + 0.01:
            return
        lines.append({
            "text": fit_text(text, text_width, font_height),
            "x": round(text_x, 2),
            "y": round(cursor, 2),
            "width": round(text_width, 2),
            "height": round(line_height, 2),
            "font_height": round(font_height, 2),
        })
        cursor += line_height + line_spacing

    # 名称与型号始终打印
    add_line(component.name, name_font, line_gap=1.2)
    add_line(component.model_number, model_font)

    if template.show_value and component.value:
        add_line(f"参数：{component.value}", body_font)

    if template.show_package:
        package_parts = []
        if component.package:
            package_parts.append(component.package)
        package_parts.append(component.get_mount_type_display())
        add_line("封装：" + " · ".join(package_parts), body_font)

    if template.show_stock:
        add_line(f"库存：{component.stock_quantity} {component.unit}", body_font)

    if template.show_location and component.storage_location:
        add_line(f"位置：{component.storage_location}", body_font)

    if template.show_batch and component.batch_number:
        add_line(f"批次：{component.batch_number}", body_font)

    if template.show_manufacturer and component.manufacturer:
        add_line(f"厂商：{component.manufacturer}", body_font)

    if template.show_category and component.category_id:
        add_line(f"品类：{component.category.name}", body_font)

    qr = None
    if qr_size:
        qr = {
            "content": get_qr_content(component, template),
            "x": round(margin if qr_on_left else width - margin - qr_size, 2),
            "y": round(margin if qr_on_top else height - margin - qr_size, 2),
            "size": round(qr_size, 2),
        }

    return {
        "width": round(width, 2),
        "height": round(height, 2),
        "margin": round(margin, 2),
        "line_spacing": round(line_spacing, 2),
        "gap_mm": round(gap_mm, 2),
        "lines": lines,
        "qr": qr,
    }




# ------------------------------------------------------------------ 打印执行


def _failure(message, printer_name="", label_count=0):
    return {
        "ok": False,
        "message": message,
        "printer_name": printer_name,
        "label_count": label_count,
    }


def _start_page(api):
    """开始新的标签页面，兼容 dtpweb 2.5.20250212 的返回值缺陷。

    该版本 ``DTPWeb.start_page()`` 在非 JSON 模式下写成了
    ``resp.statusCode``，而 ``request_api`` 实际返回 dict，因此会抛出
    ``AttributeError: 'dict' object has no attribute 'statusCode'``。
    这里临时包装 ``request_api`` 拿到真实响应，再按 statusCode 判断结果。
    """
    captured = {}
    original_request_api = api.request_api

    def capture_request_api(action, *args, **kwargs):
        response = original_request_api(action, *args, **kwargs)
        captured["response"] = response
        return response

    api.request_api = capture_request_api
    try:
        return bool(api.start_page())
    except AttributeError as exc:
        if "'dict' object has no attribute 'statusCode'" not in str(exc):
            raise
        response = captured.get("response")
        if not isinstance(response, dict) or "statusCode" not in response:
            raise
        logger.warning(
            "dtpweb start_page 返回值解析异常（已按 statusCode=%s 兼容处理）",
            response["statusCode"],
        )
        return response["statusCode"] == 0
    finally:
        api.request_api = original_request_api


def _draw_layout(api, layout):
    """把版面数据转换成 dtpweb 绘图调用，全部成功才返回 True。"""
    ok = True
    for line in layout["lines"]:
        ok = api.draw_text(
            line["text"],
            x=line["x"],
            y=line["y"],
            width=line["width"],
            height=line["height"],
            fontHeight=line["font_height"],
        ) and ok

    qr = layout.get("qr")
    if qr:
        ok = api.draw_qrcode(
            qr["content"],
            x=qr["x"],
            y=qr["y"],
            width=qr["size"],
            height=qr["size"],
        ) and ok
    return ok


def print_labels(components, template, copies=1, printer_key=""):
    """调用 dtpweb 打印标签。

    :param components: Component 可迭代对象
    :param template: LabelTemplate 实例
    :param copies: 每个元件打印份数（1~MAX_COPIES）
    :param printer_key: ``list_printers`` 返回的打印机 key；空则用第一台
    :return: ``{"ok", "message", "printer_name", "label_count"}``
    """
    components = list(components)
    try:
        copies = int(copies)
    except (TypeError, ValueError):
        copies = 1
    copies = max(1, min(copies, MAX_COPIES))
    label_count = len(components) * copies

    if not components:
        return _failure("没有需要打印的元件。")
    if label_count > MAX_LABELS:
        return _failure(f"单次最多打印 {MAX_LABELS} 张标签，当前为 {label_count} 张。")

    if getattr(settings, "DTPWEB_DRY_RUN", False):
        printer_name = _dry_run_printer()["name"]
        return {
            "ok": True,
            "message": f"演示模式：已模拟打印 {label_count} 张标签。",
            "printer_name": printer_name,
            "label_count": label_count,
        }

    try:
        from dtpweb import DTPWeb
    except ImportError:
        logger.exception("无法导入 dtpweb 模块")
        return _failure("未安装 dtpweb Python 模块，请先安装 dtpweb-*.whl。")

    # gapLength 只能通过 dtpweb 的 JSON 批量打印 jobInfo 下发；
    # 未设置标签间隔时保持原有非 JSON 流程，避免影响现有打印机。
    gap_options = get_gap_print_options(template)
    use_json_mode = "gapLength" in gap_options

    api = None
    try:
        api = DTPWeb(
            ip=getattr(settings, "DTPWEB_IP", "") or None,
            fontName=template.font_name or "黑体",
            jsonMode=use_json_mode,
        )
        if not api.check_plugin():
            return _failure(SERVICE_UNAVAILABLE_MESSAGE)

        printers = api.get_printers() or []
        if not printers:
            return _failure("没有检测到可用打印机，请检查打印机连接与驱动。")

        printer = find_printer(printers, printer_key)
        printer_name = _printer_name(printer)

        if not api.open_printer(**printer):
            return _failure(
                f"无法打开打印机「{printer_name}」，请确认打印机在线且未被其他程序占用。",
                printer_name=printer_name,
            )

        try:
            if not api.start_job(
                float(template.width_mm),
                float(template.height_mm),
                jobName="ECIMS 标签打印",
                **gap_options,
            ):
                return _failure("创建打印任务失败，请检查标签尺寸与打印机设置。", printer_name)

            for component in components:
                layout = build_label_layout(component, template)
                for _ in range(copies):
                    if not _start_page(api):
                        return _failure("开始绘制标签页面失败。", printer_name, label_count)
                    if not _draw_layout(api, layout):
                        return _failure(
                            "绘制标签内容失败，请检查模板尺寸或字体设置。",
                            printer_name,
                            label_count,
                        )
                    api.end_page()

            result = api.commit_job(**gap_options)
            if not result:
                return _failure("提交打印任务失败，请查看打印助手状态。", printer_name, label_count)
        finally:
            try:
                api.close_printer()
            except Exception:  # noqa: BLE001 - 关闭失败不影响打印结果
                logger.debug("关闭打印机失败", exc_info=True)

        return {
            "ok": True,
            "message": f"已提交 {label_count} 张标签到打印机「{printer_name}」。",
            "printer_name": printer_name,
            "label_count": label_count,
        }
    except Exception as exc:  # noqa: BLE001 - 统一转换为页面提示
        logger.exception("dtpweb 打印异常")
        return _failure(f"打印过程出错：{exc}")
