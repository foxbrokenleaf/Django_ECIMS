"""labels 应用 Excel 导出：把元件标签清单与打印记录生成 .xlsx 文件。

页面上的列表都是分页展示的，导出时按当前筛选条件导出全部数据，方便
离线核对、归档或交给其他系统使用。所有导出共用 ``build_workbook``，
保证表头样式、列宽、冻结首行与自动筛选等格式一致。
"""

import io
import unicodedata
from datetime import date, datetime
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
FALLBACK_FILENAME = "labels-export.xlsx"

SHEET_TITLE_MAX_LENGTH = 31
INVALID_SHEET_TITLE_CHARS = set('[]:*?/\\')

# 表头与单元格样式：表头沿用 Bootstrap 主色，正文统一字体、边框与对齐
_HEADER_FILL = PatternFill("solid", fgColor="0D6EFD")
_HEADER_FONT = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
_BODY_FONT = Font(name="Microsoft YaHei", size=10)
_THIN_SIDE = Side(style="thin", color="D5D9DF")
_BORDER = Border(left=_THIN_SIDE, right=_THIN_SIDE, top=_THIN_SIDE, bottom=_THIN_SIDE)
_HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center")
_BODY_ALIGNMENT = Alignment(vertical="center", wrap_text=False)

# (表头, 最小列宽)，实际列宽会按内容自动加宽
COMPONENT_EXPORT_COLUMNS = (
    ("序号", 6),
    ("元件名称", 24),
    ("型号/料号", 18),
    ("品类", 24),
    ("安装方式", 10),
    ("参数值", 18),
    ("封装", 12),
    ("制造商", 16),
    ("当前库存", 10),
    ("安全库存", 10),
    ("单位", 8),
    ("库存预警", 10),
    ("存放位置", 18),
    ("批次号", 16),
    ("元件UID", 38),
    ("更新时间", 20),
)

PRINT_RECORD_EXPORT_COLUMNS = (
    ("序号", 6),
    ("打印时间", 20),
    ("批次ID", 38),
    ("元件名称", 24),
    ("型号/料号", 18),
    ("元件UID", 38),
    ("标签模板", 18),
    ("份数", 8),
    ("打印机", 20),
    ("打印状态", 10),
    ("操作人", 12),
    ("结果信息", 40),
)


def _safe_sheet_title(title):
    """清理工作表名称：去掉 Excel 不支持的字符并限制在 31 个字符内。"""
    cleaned = "".join(
        char for char in title if char not in INVALID_SHEET_TITLE_CHARS
    ).strip()
    return (cleaned or "导出数据")[:SHEET_TITLE_MAX_LENGTH]


def build_workbook(columns, rows, sheet_title="导出数据"):
    """按列定义生成工作簿。

    ``columns`` 为 ``(表头, 最小列宽)`` 序列，``rows`` 为与列顺序一致的
    行数据序列；表头、边框、冻结首行与自动筛选在这里统一处理。
    """
    columns = list(columns)
    rows = [tuple(row) for row in rows]

    workbook = Workbook()
    workbook.properties.creator = "ECIMS"
    workbook.properties.title = sheet_title

    sheet = workbook.active
    sheet.title = _safe_sheet_title(sheet_title)

    # 表头
    for column_index, (header, _) in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=column_index, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGNMENT
        cell.border = _BORDER
    sheet.row_dimensions[1].height = 24
    sheet.freeze_panes = "A2"

    # 数据行
    for row_index, values in enumerate(rows, start=2):
        for column_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=column_index)
            if isinstance(value, str) and value.startswith("="):
                # 以 = 开头的文本按普通字符串写入，避免被 Excel 当作公式
                cell.value = value
                cell.data_type = "s"
            elif value is not None:
                cell.value = value

            cell.font = _BODY_FONT
            cell.alignment = _BODY_ALIGNMENT
            cell.border = _BORDER
            if isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
            elif isinstance(value, date):
                cell.number_format = "yyyy-mm-dd"

    # 列宽：表头与内容取较大者，再留出少量余量
    for column_index, (header, min_width) in enumerate(columns, start=1):
        content_width = max(
            [_display_width(header)]
            + [
                _display_width(row[column_index - 1])
                for row in rows
                if column_index - 1 < len(row)
            ]
        )
        width = max(min_width, min(content_width + 4, 50))
        sheet.column_dimensions[get_column_letter(column_index)].width = width

    if columns:
        sheet.auto_filter.ref = (
            f"A1:{get_column_letter(len(columns))}{max(sheet.max_row, 1)}"
        )

    return workbook


def _component_row(index, component):
    """把元件对象转换为一行导出数据，字段顺序与列定义一致。"""
    category = component.category
    return (
        index,
        component.name,
        component.model_number,
        category.full_path if category else "",
        component.get_mount_type_display(),
        component.value,
        component.package,
        component.manufacturer,
        component.stock_quantity,
        component.safety_stock,
        component.unit,
        "是" if component.is_low_stock else "否",
        component.storage_location,
        component.batch_number,
        str(component.uid),
        component.updated_at,
    )


def build_component_workbook(components):
    """生成“元件标签清单”工作簿（元件顺序与传入顺序一致）。"""
    rows = [
        _component_row(index, component)
        for index, component in enumerate(components, start=1)
    ]
    return build_workbook(
        COMPONENT_EXPORT_COLUMNS, rows, sheet_title="元件标签清单",
    )


def _print_record_row(index, record):
    """把打印记录转换为一行导出数据，字段顺序与列定义一致。"""
    operator = record.operator
    return (
        index,
        record.created_at,
        str(record.batch_id),
        record.component_name,
        record.component_model,
        str(record.component_uid) if record.component_uid else "",
        record.template_name,
        record.copies,
        record.printer_name,
        record.get_status_display(),
        operator.username if operator else "",
        record.message,
    )


def build_print_record_workbook(records):
    """生成“标签打印记录”工作簿（记录顺序与传入顺序一致）。"""
    rows = [
        _print_record_row(index, record)
        for index, record in enumerate(records, start=1)
    ]
    return build_workbook(
        PRINT_RECORD_EXPORT_COLUMNS, rows, sheet_title="标签打印记录",
    )


def export_filename(prefix):
    """生成带时间戳的导出文件名，如 元件标签清单-20261114-101530.xlsx。"""
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}.xlsx"


def xlsx_response(workbook, filename, fallback_filename=FALLBACK_FILENAME):
    """把工作簿包装成下载响应。

    中文文件名通过 RFC 5987 的 ``filename*=UTF-8''`` 传递，同时保留一个
    ASCII 文件名作为旧浏览器的兜底。
    """
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = HttpResponse(buffer.getvalue(), content_type=XLSX_CONTENT_TYPE)
    encoded_filename = quote(filename)
    response["Content-Disposition"] = (
        f'attachment; filename="{fallback_filename}"; '
        f"filename*=UTF-8''{encoded_filename}"
    )
    return response


def _display_width(value):
    """估算单元格显示宽度：中日韩字符按 2 个字符宽度计算。"""
    if value is None:
        return 0
    if isinstance(value, (datetime, date)):
        text = value.strftime("%Y-%m-%d %H:%M:%S")
    else:
        text = str(value)
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in text
    )
