"""labels 应用测试：版面组装、dtpweb 演示模式打印、模板与记录视图。"""

import sys
import types
import uuid
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from components.models import Category, Component

from .exports import XLSX_CONTENT_TYPE
from .forms import LabelPrintSettingsForm
from .models import LabelPrintRecord, LabelTemplate
from .services import (
    MAX_LABELS,
    build_label_layout,
    fit_text,
    get_gap_print_options,
    get_qr_content,
    list_printers,
    print_labels,
)

User = get_user_model()


def make_template(**kwargs):
    """构造未入库的模板实例（模型字段均有默认值）。"""
    data = {
        "name": "标准标签",
        "width_mm": Decimal("40.0"),
        "height_mm": Decimal("30.0"),
    }
    data.update(kwargs)
    return LabelTemplate(**data)


def make_component(**kwargs):
    """构造未入库的元件实例，仅用于无需数据库的版面测试。"""
    data = {
        "name": "贴片电阻",
        "model_number": "RC0603-10K",
        "value": "10kΩ",
        "package": "0603",
        "stock_quantity": 100,
        "safety_stock": 20,
        "unit": "个",
        "storage_location": "A柜-1层-05格",
        "batch_number": "B202401",
        "manufacturer": "Yageo",
    }
    data.update(kwargs)
    return Component(**data)


class LabelLayoutTests(SimpleTestCase):
    """build_label_layout / fit_text / get_qr_content 纯计算逻辑。"""

    def setUp(self):
        self.component = make_component()
        self.template = make_template()

    def test_layout_contains_name_and_model(self):
        layout = build_label_layout(self.component, self.template)
        texts = [line["text"] for line in layout["lines"]]
        self.assertEqual(texts[0], "贴片电阻")
        self.assertEqual(texts[1], "RC0603-10K")
        self.assertEqual(layout["width"], 40.0)
        self.assertEqual(layout["height"], 30.0)

    def test_layout_stays_inside_label(self):
        layout = build_label_layout(self.component, self.template)
        for line in layout["lines"]:
            self.assertGreaterEqual(line["x"], 0)
            self.assertGreaterEqual(line["y"], 0)
            self.assertLessEqual(line["x"] + line["width"], layout["width"] + 0.01)
            self.assertLessEqual(line["y"] + line["height"], layout["height"] + 0.01)
        qr = layout["qr"]
        self.assertIsNotNone(qr)
        self.assertLessEqual(qr["x"] + qr["size"], layout["width"] + 0.01)
        self.assertLessEqual(qr["y"] + qr["size"], layout["height"] + 0.01)

    def test_qr_defaults_to_uid(self):
        layout = build_label_layout(self.component, self.template)
        self.assertEqual(layout["qr"]["content"], str(self.component.uid))

    def test_qr_can_use_model_number(self):
        template = make_template(qr_content=LabelTemplate.QrContent.MODEL)
        self.assertEqual(get_qr_content(self.component, template), "RC0603-10K")

    def test_qr_can_use_name_and_model(self):
        template = make_template(qr_content=LabelTemplate.QrContent.NAME_MODEL)
        self.assertEqual(get_qr_content(self.component, template), "贴片电阻 RC0603-10K")

    def test_disable_qr(self):
        layout = build_label_layout(self.component, make_template(include_qr=False))
        self.assertIsNone(layout["qr"])

    def test_field_toggles(self):
        template = make_template(show_stock=False, show_batch=False, show_location=False)
        texts = [line["text"] for line in build_label_layout(self.component, template)["lines"]]
        self.assertNotIn("库存：100 个", texts)
        self.assertNotIn("批次：B202401", texts)
        self.assertNotIn("位置：A柜-1层-05格", texts)
        self.assertIn("参数：10kΩ", texts)

    def test_mount_type_is_printed_with_package(self):
        layout = build_label_layout(self.component, self.template)
        texts = [line["text"] for line in layout["lines"]]
        self.assertTrue(any(text.startswith("封装：0603") for text in texts))

    def test_long_text_is_truncated(self):
        text = fit_text("超长元件名称" * 10, max_width_mm=10, font_height_mm=2)
        self.assertTrue(text.endswith("…"))
        self.assertLess(len(text), 60)

    def test_short_text_is_not_truncated(self):
        self.assertEqual(fit_text("10kΩ", 40, 2), "10kΩ")

    def test_custom_margin_and_line_spacing(self):
        template = make_template(
            margin_mm=Decimal("3.0"), line_spacing_mm=Decimal("1.0"),
        )
        layout = build_label_layout(self.component, template)

        self.assertEqual(layout["margin"], 3.0)
        self.assertEqual(layout["line_spacing"], 1.0)
        self.assertEqual(layout["lines"][0]["x"], 3.0)
        first, second = layout["lines"][:2]
        self.assertGreaterEqual(
            second["y"], first["y"] + first["height"] + 1.0 - 0.01,
        )

    def test_font_scale_changes_font_height(self):
        normal = build_label_layout(self.component, self.template)
        large = build_label_layout(
            self.component, make_template(font_scale=Decimal("1.5")),
        )
        self.assertGreater(
            large["lines"][0]["font_height"], normal["lines"][0]["font_height"],
        )

    def test_qr_size_and_position_are_configurable(self):
        template = make_template(
            qr_size_mm=Decimal("8.0"),
            qr_position=LabelTemplate.QrPosition.TOP_LEFT,
        )
        layout = build_label_layout(self.component, template)

        self.assertEqual(layout["qr"]["size"], 8.0)
        self.assertEqual(layout["qr"]["x"], layout["margin"])
        self.assertEqual(layout["qr"]["y"], layout["margin"])

    def test_qr_position_bottom_left(self):
        template = make_template(
            qr_position=LabelTemplate.QrPosition.BOTTOM_LEFT,
        )
        layout = build_label_layout(self.component, template)
        qr = layout["qr"]

        self.assertEqual(qr["x"], layout["margin"])
        self.assertAlmostEqual(
            qr["y"] + qr["size"], layout["height"] - layout["margin"], places=2,
        )

    def test_layout_contains_gap_setting(self):
        layout = build_label_layout(
            self.component, make_template(gap_mm=Decimal("2.0")),
        )
        self.assertEqual(layout["gap_mm"], 2.0)

    def test_gap_print_options(self):
        self.assertEqual(get_gap_print_options(make_template()), {})
        self.assertEqual(
            get_gap_print_options(make_template(gap_type=LabelTemplate.GapType.GAP)),
            {"gapType": 2},
        )
        self.assertEqual(
            get_gap_print_options(
                make_template(
                    gap_type=LabelTemplate.GapType.BLACK,
                    gap_mm=Decimal("3.5"),
                )
            ),
            {"gapType": 3, "gapLength": 3.5},
        )


@override_settings(DTPWEB_DRY_RUN=True)
class DryRunServiceTests(SimpleTestCase):
    """DTPWEB_DRY_RUN 下不接触 dtpweb，仅验证业务编排。"""

    def test_list_printers_returns_demo_printer(self):
        info = list_printers()
        self.assertTrue(info["service_available"])
        self.assertEqual(info["default_printer"], "dry-run|演示打印机")
        self.assertEqual(info["printers"][0]["type_label"], "演示")
        self.assertEqual(info["error"], "")

    def test_print_labels_counts_copies(self):
        template = make_template()
        components = [make_component(), make_component(name="贴片电容")]
        result = print_labels(components, template, copies=3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["label_count"], 6)
        self.assertIn("演示打印机", result["printer_name"])

    def test_copies_is_clamped_to_at_least_one(self):
        result = print_labels([make_component()], make_template(), copies=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["label_count"], 1)

    def test_empty_selection_fails(self):
        result = print_labels([], make_template(), copies=1)
        self.assertFalse(result["ok"])
        self.assertIn("没有需要打印的元件", result["message"])

    def test_too_many_labels_fails(self):
        components = [make_component() for _ in range(6)]
        result = print_labels(components, make_template(), copies=100)
        self.assertFalse(result["ok"])
        self.assertIn(str(MAX_LABELS), result["message"])


class FakeDTPWeb:
    """模拟 dtpweb.DTPWeb，验证打印编排而不依赖打印助手。"""

    commit_result = True
    start_page_bug = False
    start_page_status = 0
    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.json_mode = bool(kwargs.get("jsonMode"))
        self.pages = 0
        self.closed = False
        self.job_kwargs = {}
        self.commit_kwargs = {}
        FakeDTPWeb.last_instance = self

    def check_plugin(self):
        return True

    def get_printers(self):
        return [{"name": "测试打印机", "type": 1, "ip": ""}]

    def open_printer(self, **kwargs):
        self.printer = kwargs
        return True

    def request_api(self, action, *args, **kwargs):
        """模拟 SDK 的 HTTP 响应。"""
        return {"statusCode": self.start_page_status, "resultInfo": {}}

    def start_job(self, width, height, **kwargs):
        self.job_size = (width, height)
        self.job_kwargs = kwargs
        return True

    def start_page(self):
        response = self.request_api("start_page")
        self.pages += 1
        if self.start_page_bug:
            # 复现 dtpweb 2.5.20250212 对 dict 使用 .statusCode 的缺陷
            return response.statusCode == 0  # noqa: B018
        return response["statusCode"] == 0

    def draw_text(self, *args, **kwargs):
        return True

    def draw_qrcode(self, *args, **kwargs):
        return True

    def end_page(self):
        return True

    def commit_job(self, **kwargs):
        self.commit_kwargs = kwargs
        return self.commit_result

    def close_printer(self):
        self.closed = True


@override_settings(DTPWEB_DRY_RUN=False)
class DTPWebServiceTests(SimpleTestCase):
    """真实 SDK 分支：通过假 dtpweb 模块验证调用顺序与失败处理。"""

    def setUp(self):
        FakeDTPWeb.commit_result = True
        FakeDTPWeb.start_page_bug = False
        FakeDTPWeb.start_page_status = 0
        self.module = types.ModuleType("dtpweb")
        self.module.DTPWeb = FakeDTPWeb
        patcher = patch.dict(sys.modules, {"dtpweb": self.module})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_print_calls_sdk_and_returns_success(self):
        template = make_template(font_name="微软雅黑")
        result = print_labels([make_component()], template, copies=2)

        self.assertTrue(result["ok"])
        self.assertEqual(result["label_count"], 2)
        self.assertEqual(result["printer_name"], "测试打印机")

        api = FakeDTPWeb.last_instance
        self.assertEqual(api.kwargs["fontName"], "微软雅黑")
        self.assertFalse(api.json_mode)
        self.assertEqual(api.job_size, (40.0, 30.0))
        self.assertEqual(api.pages, 2)
        self.assertTrue(api.closed)
        self.assertEqual(api.commit_kwargs, {})

    def test_gap_length_uses_json_mode_and_is_forwarded(self):
        template = make_template(
            gap_type=LabelTemplate.GapType.GAP,
            gap_mm=Decimal("2.0"),
        )
        result = print_labels([make_component()], template)

        self.assertTrue(result["ok"])
        api = FakeDTPWeb.last_instance
        self.assertTrue(api.json_mode)
        self.assertEqual(api.job_kwargs["gapType"], 2)
        self.assertEqual(api.job_kwargs["gapLength"], 2.0)
        self.assertEqual(api.commit_kwargs["gapType"], 2)
        self.assertEqual(api.commit_kwargs["gapLength"], 2.0)

    def test_gap_type_without_length_keeps_non_json_mode(self):
        template = make_template(
            gap_type=LabelTemplate.GapType.NONE,
            gap_mm=Decimal("0.0"),
        )
        result = print_labels([make_component()], template)

        self.assertTrue(result["ok"])
        api = FakeDTPWeb.last_instance
        self.assertFalse(api.json_mode)
        self.assertEqual(api.commit_kwargs, {"gapType": 0})
        self.assertNotIn("gapLength", api.job_kwargs)

    def test_commit_failure_is_reported(self):
        FakeDTPWeb.commit_result = False
        result = print_labels([make_component()], make_template())

        self.assertFalse(result["ok"])
        self.assertIn("提交打印任务失败", result["message"])
        self.assertTrue(FakeDTPWeb.last_instance.closed)

    def test_start_page_sdk_bug_is_worked_around(self):
        FakeDTPWeb.start_page_bug = True
        with self.assertLogs("labels.services", level="WARNING") as logs:
            result = print_labels([make_component()], make_template(), copies=2)

        self.assertTrue(result["ok"])
        self.assertEqual(FakeDTPWeb.last_instance.pages, 2)
        self.assertIn("start_page", "".join(logs.output))

    def test_start_page_failure_with_sdk_bug_is_reported(self):
        FakeDTPWeb.start_page_bug = True
        FakeDTPWeb.start_page_status = 1
        with self.assertLogs("labels.services", level="WARNING"):
            result = print_labels([make_component()], make_template())

        self.assertFalse(result["ok"])
        self.assertIn("开始绘制标签页面失败", result["message"])
        self.assertTrue(FakeDTPWeb.last_instance.closed)


class LabelTemplateModelTests(TestCase):
    """模板默认标记与 get_default 兜底逻辑。"""

    def test_only_one_default_template(self):
        first = LabelTemplate.objects.create(name="模板A", is_default=True)
        second = LabelTemplate.objects.create(name="模板B", is_default=True)
        first.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(LabelTemplate.get_default(), second)

    def test_get_default_falls_back_to_active_template(self):
        LabelTemplate.objects.create(name="停用模板", is_active=False)
        active = LabelTemplate.objects.create(name="启用模板", is_active=True)
        self.assertEqual(LabelTemplate.get_default(), active)

    def test_get_default_without_templates(self):
        self.assertIsNone(LabelTemplate.get_default())


class LabelPrintSettingsFormTests(TestCase):
    """打印参数表单：只允许启用模板，份数受上限约束。"""

    def setUp(self):
        self.active = LabelTemplate.objects.create(name="启用模板")
        self.inactive = LabelTemplate.objects.create(name="停用模板", is_active=False)

    def test_inactive_template_is_rejected(self):
        form = LabelPrintSettingsForm(
            data={"template": self.inactive.pk, "copies": 1, "printer": ""}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("template", form.errors)

    def test_copies_above_limit_is_rejected(self):
        form = LabelPrintSettingsForm(
            data={"template": self.active.pk, "copies": MAX_LABELS + 1, "printer": ""}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("copies", form.errors)

    def test_printer_choices_include_default_option(self):
        form = LabelPrintSettingsForm(
            printers=[{"key": "1|标签机", "name": "标签机", "type": "1", "type_label": "本地"}]
        )
        self.assertEqual(form.fields["printer"].choices[0], ("", "自动选择默认打印机"))
        self.assertIn(("1|标签机", "标签机（本地）"), form.fields["printer"].choices)


@override_settings(DTPWEB_DRY_RUN=True)
class LabelViewTests(TestCase):
    """页面视图：筛选、预览、打印落库、历史权限与模板维护权限。"""

    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="电阻", code="RES")
        cls.component = Component.objects.create(
            name="贴片电阻", model_number="RC0603-10K", category=cls.category,
            value="10kΩ", package="0603", stock_quantity=100, safety_stock=20, unit="个",
        )
        cls.other_component = Component.objects.create(
            name="别人的元件", model_number="OTHER-1", category=cls.category,
            stock_quantity=5, safety_stock=20,
        )
        cls.template = LabelTemplate.objects.create(
            name="标准模板", width_mm=40, height_mm=30, is_default=True,
        )

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw12345678")
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "pw12345678")

    def login(self, user=None):
        self.client.force_login(user or self.user)

    def test_home_requires_login(self):
        response = self.client.get(reverse("labels:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_home_keyword_filter(self):
        self.login()
        response = self.client.get(reverse("labels:home"), {"q": "RC0603"})
        self.assertContains(response, "贴片电阻")
        self.assertNotContains(response, "别人的元件")

    def test_home_low_stock_filter(self):
        self.login()
        response = self.client.get(reverse("labels:home"), {"low_stock": "1"})
        self.assertContains(response, "别人的元件")
        self.assertNotContains(response, "贴片电阻")

    @override_settings(DTPWEB_DRY_RUN=True)
    def test_printer_status_api(self):
        self.login()
        response = self.client.get(reverse("labels:printers"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["service_available"])
        self.assertEqual(payload["printers"][0]["name"], "演示打印机（DTPWEB_DRY_RUN）")

    def test_preview_renders_layout(self):
        self.login()
        response = self.client.get(reverse("labels:preview", args=[self.component.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "标签预览")
        self.assertContains(response, "RC0603-10K")
        self.assertContains(response, "10kΩ")
        self.assertContains(response, "标签间隔")

    @override_settings(DTPWEB_DRY_RUN=True)
    def test_print_creates_one_record_per_component(self):
        self.login()
        response = self.client.post(
            reverse("labels:print"),
            {
                "component": [self.component.pk, self.other_component.pk],
                "template": self.template.pk,
                "copies": 2,
                "printer": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        records = LabelPrintRecord.objects.filter(operator=self.user)
        self.assertEqual(records.count(), 2)
        record = records.get(component=self.component)
        self.assertEqual(record.copies, 2)
        self.assertEqual(record.status, LabelPrintRecord.Status.SUCCESS)
        self.assertEqual(record.component_name, "贴片电阻")
        self.assertEqual(record.template_name, "标准模板")
        self.assertIn("演示模式", record.message)
        self.assertEqual(records.values("batch_id").distinct().count(), 1)

    @override_settings(DTPWEB_DRY_RUN=True)
    def test_print_without_selection_creates_nothing(self):
        self.login()
        response = self.client.post(reverse("labels:print"), {}, follow=True)
        self.assertContains(response, "请先勾选需要打印标签的元件")
        self.assertEqual(LabelPrintRecord.objects.count(), 0)

    def test_history_only_shows_own_records_for_normal_user(self):
        LabelPrintRecord.objects.create(
            component=self.component, component_name="自己的打印", operator=self.user,
        )
        LabelPrintRecord.objects.create(
            component=self.other_component, component_name="他人的打印", operator=self.admin,
        )
        self.login()
        response = self.client.get(reverse("labels:history"))
        self.assertContains(response, "自己的打印")
        self.assertNotContains(response, "他人的打印")

    def test_history_shows_all_records_for_staff(self):
        LabelPrintRecord.objects.create(
            component=self.component, component_name="自己的打印", operator=self.user,
        )
        LabelPrintRecord.objects.create(
            component=self.other_component, component_name="他人的打印", operator=self.admin,
        )
        self.login(self.admin)
        response = self.client.get(reverse("labels:history"))
        self.assertContains(response, "自己的打印")
        self.assertContains(response, "他人的打印")

    def test_scan_by_uid(self):
        self.login()
        response = self.client.get(reverse("labels:scan", args=[self.component.uid]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "贴片电阻")

    def test_scan_unknown_uid_returns_404(self):
        self.login()
        response = self.client.get(reverse("labels:scan", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 404)

    def test_template_list_visible_to_normal_user(self):
        self.login()
        response = self.client.get(reverse("labels:template_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "标准模板")

    def test_normal_user_cannot_create_or_edit_templates(self):
        self.login()
        data = {"name": "越权模板", "width_mm": "40", "height_mm": "30",
                "font_name": "黑体", "qr_content": "uid", "default_copies": 1}
        self.assertEqual(
            self.client.post(reverse("labels:template_create"), data).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("labels:template_edit", args=[self.template.pk]), data
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("labels:template_toggle", args=[self.template.pk])
            ).status_code,
            403,
        )
        self.assertFalse(LabelTemplate.objects.filter(name="越权模板").exists())
        self.template.refresh_from_db()
        self.assertTrue(self.template.is_active)

    def test_superuser_can_create_template(self):
        self.login(self.admin)
        form_page = self.client.get(reverse("labels:template_create"))
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, "新建标签模板")
        self.assertContains(form_page, "版面设置")
        self.assertContains(form_page, "标签间隔")

        response = self.client.post(
            reverse("labels:template_create"),
            {
                "name": "新模板", "description": "测试创建", "width_mm": "50",
                "height_mm": "40", "font_name": "黑体", "include_qr": "on",
                "qr_content": "uid", "qr_size_mm": "10.0",
                "qr_position": "top_right", "margin_mm": "2.0",
                "line_spacing_mm": "0.6", "font_scale": "1.1",
                "gap_type": "gap", "gap_mm": "2.0", "default_copies": "2",
                "is_default": "on", "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("labels:template_list"))
        created = LabelTemplate.objects.get(name="新模板")
        self.assertTrue(created.is_active)
        self.assertTrue(created.is_default)
        self.assertEqual(created.default_copies, 2)
        self.assertEqual(float(created.margin_mm), 2.0)
        self.assertEqual(float(created.line_spacing_mm), 0.6)
        self.assertEqual(float(created.font_scale), 1.1)
        self.assertEqual(float(created.qr_size_mm), 10.0)
        self.assertEqual(created.qr_position, "top_right")
        self.assertEqual(created.gap_type, "gap")
        self.assertEqual(float(created.gap_mm), 2.0)
        self.template.refresh_from_db()
        self.assertFalse(self.template.is_default)

    def test_superuser_can_edit_template(self):
        self.login(self.admin)
        form_page = self.client.get(
            reverse("labels:template_edit", args=[self.template.pk])
        )
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, "编辑标签模板")

        response = self.client.post(
            reverse("labels:template_edit", args=[self.template.pk]),
            {
                "name": "标准模板V2", "width_mm": "60", "height_mm": "40",
                "font_name": "微软雅黑", "qr_content": "model",
                "qr_size_mm": "0", "qr_position": "bottom_left",
                "margin_mm": "2.5", "line_spacing_mm": "0.8", "font_scale": "0.9",
                "gap_type": "none", "gap_mm": "0",
                "default_copies": "5", "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("labels:template_list"))
        self.template.refresh_from_db()
        self.assertEqual(self.template.name, "标准模板V2")
        self.assertEqual(self.template.default_copies, 5)
        self.assertEqual(float(self.template.width_mm), 60.0)
        self.assertEqual(float(self.template.margin_mm), 2.5)
        self.assertEqual(float(self.template.line_spacing_mm), 0.8)
        self.assertEqual(float(self.template.font_scale), 0.9)
        self.assertEqual(float(self.template.gap_mm), 0.0)
        self.assertEqual(self.template.gap_type, "none")
        self.assertEqual(self.template.qr_position, "bottom_left")
        self.assertFalse(self.template.include_qr)

    def test_superuser_can_toggle_template(self):
        self.login(self.admin)
        response = self.client.post(
            reverse("labels:template_toggle", args=[self.template.pk])
        )
        self.assertRedirects(response, reverse("labels:template_list"))
        self.template.refresh_from_db()
        self.assertFalse(self.template.is_active)
        self.assertFalse(self.template.is_default)


class LabelExportTests(TestCase):
    """Excel 导出：登录校验、筛选条件、权限范围与文件格式。"""

    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="电阻", code="RES-EXP")
        cls.component = Component.objects.create(
            name="贴片电阻", model_number="RC0603-10K-EXP", category=cls.category,
            value="10kΩ", package="0603", stock_quantity=100, safety_stock=20,
            unit="个", storage_location="A柜-1层", batch_number="B202401",
        )
        cls.other_component = Component.objects.create(
            name="别人的元件", model_number="OTHER-EXP-1", category=cls.category,
            stock_quantity=5, safety_stock=20,
        )
        cls.template = LabelTemplate.objects.create(
            name="导出模板", width_mm=40, height_mm=30, is_default=True,
        )

    def setUp(self):
        self.user = User.objects.create_user("exporter", password="pw12345678")
        self.admin = User.objects.create_superuser(
            "export-admin", "export-admin@example.com", "pw12345678",
        )
        LabelPrintRecord.objects.create(
            batch_id=uuid.uuid4(),
            component=self.component,
            component_name=self.component.name,
            component_model=self.component.model_number,
            component_uid=self.component.uid,
            template=self.template,
            template_name=self.template.name,
            copies=2,
            printer_name="测试打印机",
            status=LabelPrintRecord.Status.SUCCESS,
            message="打印成功",
            operator=self.user,
        )
        LabelPrintRecord.objects.create(
            batch_id=uuid.uuid4(),
            component=self.other_component,
            component_name=self.other_component.name,
            component_model=self.other_component.model_number,
            component_uid=self.other_component.uid,
            template=self.template,
            template_name=self.template.name,
            copies=1,
            printer_name="测试打印机",
            status=LabelPrintRecord.Status.FAILED,
            message="缺纸",
            operator=self.admin,
        )

    def login(self, user=None):
        self.client.force_login(user or self.user)

    @staticmethod
    def load_sheet(response):
        return load_workbook(BytesIO(response.content)).active

    def test_component_export_requires_login(self):
        response = self.client.get(reverse("labels:export_components"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_component_export_returns_filtered_workbook(self):
        self.login()
        response = self.client.get(
            reverse("labels:export_components"), {"q": "RC0603-10K-EXP"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX_CONTENT_TYPE)
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("filename*=UTF-8''", response["Content-Disposition"])

        sheet = self.load_sheet(response)
        self.assertEqual(sheet.title, "元件标签清单")
        headers = [cell.value for cell in sheet[1]]
        self.assertEqual(headers[0], "序号")
        self.assertIn("元件名称", headers)
        self.assertIn("元件UID", headers)
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertIsNotNone(sheet.auto_filter.ref)

        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "贴片电阻")
        self.assertEqual(rows[0][2], "RC0603-10K-EXP")
        self.assertEqual(rows[0][11], "否")

    def test_component_export_honours_low_stock_filter(self):
        self.login()
        response = self.client.get(
            reverse("labels:export_components"), {"low_stock": "1"},
        )
        rows = list(self.load_sheet(response).iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "别人的元件")
        self.assertEqual(rows[0][11], "是")

    def test_history_export_requires_login(self):
        response = self.client.get(reverse("labels:export_history"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_history_export_only_contains_own_records_for_normal_user(self):
        self.login()
        response = self.client.get(reverse("labels:export_history"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], XLSX_CONTENT_TYPE)

        sheet = self.load_sheet(response)
        self.assertEqual(sheet.title, "标签打印记录")
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "贴片电阻")
        self.assertEqual(rows[0][9], "打印成功")
        self.assertEqual(rows[0][10], "exporter")
        self.assertIsInstance(rows[0][1], datetime)

    def test_history_export_for_staff_contains_all_records(self):
        self.login(self.admin)
        response = self.client.get(reverse("labels:export_history"))
        rows = list(self.load_sheet(response).iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 2)

    def test_history_export_applies_status_filter(self):
        self.login(self.admin)
        response = self.client.get(
            reverse("labels:export_history"), {"status": "failed"},
        )
        rows = list(self.load_sheet(response).iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "别人的元件")
        self.assertEqual(rows[0][9], "打印失败")

    def test_pages_show_export_buttons(self):
        self.login()
        home = self.client.get(reverse("labels:home"), {"q": "RC0603"})
        self.assertContains(home, "导出 Excel")
        self.assertContains(home, reverse("labels:export_components"))
        self.assertContains(home, "?q=RC0603")

        history = self.client.get(reverse("labels:history"), {"status": "success"})
        self.assertContains(history, "导出 Excel")
        self.assertContains(history, reverse("labels:export_history"))
        self.assertContains(history, "?status=success")



