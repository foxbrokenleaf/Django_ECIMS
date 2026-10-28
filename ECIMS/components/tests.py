"""components 应用测试：模板标签库 component_extras + 品类/元件管理视图。"""

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Category, Component, StockRecord

LOAD_TAGS = "{% load component_extras %}"


def render_tag(source, **context):
    """渲染一段带 component_extras 的模板片段，返回渲染结果。"""
    return Template(LOAD_TAGS + source).render(Context(context))


class QuerystringTagTests(SimpleTestCase):
    """{% querystring %} 保留 / 覆盖 / 移除 URL 参数。"""

    def setUp(self):
        self.request = SimpleNamespace(GET=QueryDict("q=电阻&page=2"))

    def test_keeps_existing_params(self):
        params = QueryDict(render_tag("{% querystring page=3 %}", request=self.request))
        self.assertEqual(params["q"], "电阻")
        self.assertEqual(params["page"], "3")

    def test_empty_value_removes_param(self):
        params = QueryDict(render_tag("{% querystring page='' %}", request=self.request))
        self.assertEqual(params["q"], "电阻")
        self.assertNotIn("page", params)

    def test_works_without_request(self):
        self.assertEqual(render_tag("{% querystring page=1 %}"), "page=1")


class NavActiveTagTests(SimpleTestCase):
    """{% nav_active %} 导航高亮，支持视图名前缀匹配。"""

    def _render(self, view_name, *names):
        request = SimpleNamespace(resolver_match=SimpleNamespace(view_name=view_name))
        source = "{% nav_active " + " ".join(f"'{n}'" for n in names) + " %}"
        return render_tag(source, request=request)

    def test_prefix_match_detail_page(self):
        self.assertEqual(self._render("components:category_detail", "components:category"), "active")

    def test_exact_match(self):
        self.assertEqual(self._render("components:category_list", "components:category_list"), "active")

    def test_no_match_returns_empty(self):
        self.assertEqual(self._render("components:component_list", "components:category"), "")

    def test_missing_resolver_match(self):
        self.assertEqual(render_tag("{% nav_active 'components:category' %}"), "")


class StockBadgeTagTests(SimpleTestCase):
    """{% stock_badge %} 库存徽章渲染。模型实例无需入库。"""

    def test_low_stock_shows_danger_badge(self):
        component = Component(
            name="贴片电阻", model_number="RC0603-10K",
            stock_quantity=5, safety_stock=20,
        )
        html = render_tag("{% stock_badge component %}", component=component)
        self.assertIn("bg-danger-subtle", html)
        self.assertIn("5 个", html)
        self.assertIn('title="安全库存 20"', html)

    def test_normal_stock_shows_success_badge(self):
        component = Component(
            name="贴片电阻", model_number="RC0603-10K",
            stock_quantity=100, safety_stock=20,
        )
        html = render_tag("{% stock_badge component %}", component=component)
        self.assertIn("bg-success-subtle", html)
        self.assertIn("100 个", html)

    def test_without_unit(self):
        component = Component(
            name="贴片电阻", model_number="RC0603-10K",
            stock_quantity=5, safety_stock=20,
        )
        html = render_tag("{% stock_badge component False %}", component=component)
        self.assertIn("5</span>", html)


class RecordTypeBadgeTagTests(SimpleTestCase):
    """{% record_type_badge %} 出入库类型徽章。"""

    def test_in_badge(self):
        html = render_tag("{% record_type_badge record %}", record=StockRecord(record_type="IN"))
        self.assertIn("bg-success-subtle", html)
        self.assertIn("入库", html)

    def test_out_badge(self):
        html = render_tag("{% record_type_badge record %}", record=StockRecord(record_type="OUT"))
        self.assertIn("bg-danger-subtle", html)
        self.assertIn("出库", html)

    def test_adjust_badge(self):
        html = render_tag("{% record_type_badge record %}", record=StockRecord(record_type="ADJUST"))
        self.assertIn("bg-warning-subtle", html)
        self.assertIn("盘点调整", html)

    def test_unknown_type_falls_back(self):
        html = render_tag("{% record_type_badge record %}", record=StockRecord(record_type="XX"))
        self.assertIn("bg-secondary-subtle", html)


class CategoryListViewTests(TestCase):
    """品类列表：分页参数与搜索条件配合 querystring 标签。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="tester", password="test-pass-123"
        )
        Category.objects.bulk_create([
            Category(name=f"品类{i:02d}", code=f"C{i:03d}")
            for i in range(25)
        ])

    def setUp(self):
        self.client.force_login(self.user)

    def test_first_page_paginated(self):
        response = self.client.get(reverse("components:category_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(len(response.context["categories"]), 20)
        # 侧边栏由 {% nav_active 'components:category' %} 高亮
        self.assertIn(b"nav-link active", response.content)

    def test_second_page_has_rest_and_keeps_query(self):
        response = self.client.get(reverse("components:category_list"), {"q": "品类"})
        self.assertEqual(len(response.context["categories"]), 20)

        response = self.client.get(
            reverse("components:category_list"), {"q": "品类", "page": 2}
        )
        self.assertEqual(len(response.context["categories"]), 5)
        # 分页链接由 {% querystring %} 生成，应同时保留 q 与 page，且未被 HTML 转义
        self.assertIn(b"&page=1", response.content)
        self.assertNotIn(b"&amp;page=1", response.content)
        self.assertIn(b"q=", response.content)

    def test_invalid_page_falls_back_to_last(self):
        response = self.client.get(reverse("components:category_list"), {"page": 999})
        self.assertEqual(response.context["page_obj"].number, 2)

    def test_detail_page_renders_children_and_components(self):
        parent = Category.objects.create(name="电阻", code="RES-D")
        child = Category.objects.create(name="贴片电阻", code="RES-D-SMD", parent=parent)
        Component.objects.create(
            name="贴片电阻 1kΩ", model_number="RC-D-1K",
            category=child, stock_quantity=100, safety_stock=10,
        )
        response = self.client.get(
            reverse("components:category_detail", args=[parent.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "子品类")
        self.assertContains(response, "贴片电阻")

        # 元件挂在子品类下，子品类页应渲染该元件及库存徽章
        response = self.client.get(
            reverse("components:category_detail", args=[child.pk])
        )
        self.assertContains(response, "贴片电阻 1kΩ")
        self.assertContains(response, "bg-success-subtle")


class ComponentViewTests(TestCase):
    """元件管理：列表筛选、增改停用、出入库登记。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="engineer", password="test-pass-123"
        )
        cls.root = Category.objects.create(name="电阻", code="RES")
        cls.child = Category.objects.create(name="贴片电阻", code="RES-SMD", parent=cls.root)
        cls.other = Category.objects.create(name="电容", code="CAP")

        cls.resistor = Component.objects.create(
            name="贴片电阻 10kΩ", model_number="RC0603-10K", category=cls.child,
            manufacturer="Yageo", package="0603", value="10kΩ",
            stock_quantity=5, safety_stock=20,
        )
        cls.capacitor = Component.objects.create(
            name="贴片电容 100nF", model_number="CC0603-100N", category=cls.other,
            manufacturer="Samsung", package="0603", value="100nF",
            stock_quantity=500, safety_stock=100,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def form_data(self, **overrides):
        data = {
            "name": "贴片电阻 4.7kΩ",
            "model_number": "RC0603-4K7",
            "category": self.child.pk,
            "manufacturer": "Yageo",
            "description": "常用分压电阻",
            "package": "0603",
            "mount_type": "SMD",
            "value": "4.7kΩ",
            "tolerance": "1%",
            "voltage_rating": "50V",
            "power_rating": "0.1W",
            "extra_specs": '{"温度系数": "±100ppm"}',
            "safety_stock": 20,
            "unit": "个",
            "storage_location": "A柜-3层-05格",
            "batch_number": "B2026",
            "reference_price": "0.0100",
            "supplier": "立创商城",
            "is_active": "on",
            "initial_stock": 30,
        }
        data.update(overrides)
        return data

    # ---- 列表与筛选 ----

    def test_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("components:component_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_list_shows_components_with_stock_badge(self):
        response = self.client.get(reverse("components:component_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_count"], 2)
        self.assertContains(response, "贴片电阻 10kΩ")
        # 低库存（5 <= 20）应渲染红色徽章
        self.assertContains(response, "bg-danger-subtle")
        self.assertContains(response, 'title="安全库存 20"')

    def test_list_search_matches_model_number(self):
        response = self.client.get(reverse("components:component_list"), {"q": "RC0603"})
        names = [c.name for c in response.context["components"]]
        self.assertEqual(names, ["贴片电阻 10kΩ"])

    def test_list_filters_by_parent_category(self):
        response = self.client.get(
            reverse("components:component_list"), {"category": self.root.pk}
        )
        names = [c.name for c in response.context["components"]]
        self.assertEqual(names, ["贴片电阻 10kΩ"])

    def test_list_filters_low_stock_only(self):
        response = self.client.get(reverse("components:component_list"), {"low_stock": "1"})
        self.assertEqual(response.context["total_count"], 1)
        self.assertEqual(response.context["low_stock_count"], 1)
        self.assertNotContains(response, "贴片电容 100nF")

    def test_list_filters_mount_type(self):
        response = self.client.get(
            reverse("components:component_list"), {"mount_type": "THT"}
        )
        self.assertEqual(response.context["total_count"], 0)

    def test_list_paginates_and_keeps_filters(self):
        Component.objects.bulk_create([
            Component(
                name=f"批量元件{i:02d}", model_number=f"BULK-{i:03d}",
                category=self.child, manufacturer="Bulk",
            )
            for i in range(25)
        ])
        response = self.client.get(
            reverse("components:component_list"), {"q": "批量", "page": 2}
        )
        self.assertEqual(response.context["total_count"], 25)
        self.assertEqual(len(response.context["components"]), 5)
        # 分页链接保留搜索条件且未被 HTML 转义
        self.assertContains(response, "q=")
        self.assertNotContains(response, "&amp;page=1")
        self.assertContains(response, "page=1")


    # ---- 新增 / 编辑 / 停用 ----

    def test_create_component_with_initial_stock(self):
        response = self.client.post(reverse("components:component_create"), self.form_data())
        component = Component.objects.get(model_number="RC0603-4K7")

        self.assertRedirects(
            response, reverse("components:component_detail", args=[component.pk])
        )
        self.assertEqual(component.created_by, self.user)
        self.assertEqual(component.stock_quantity, 30)
        self.assertEqual(component.extra_specs, {"温度系数": "±100ppm"})

        record = component.stock_records.get()
        self.assertEqual(record.record_type, StockRecord.RecordType.IN)
        self.assertEqual(record.quantity, 30)
        self.assertEqual(record.quantity_after, 30)
        self.assertEqual(record.operator, self.user)

    def test_create_duplicate_model_and_manufacturer_rejected(self):
        response = self.client.post(
            reverse("components:component_create"),
            self.form_data(model_number="RC0603-10K", manufacturer="Yageo"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("已存在", str(response.context["form"].non_field_errors()))
        self.assertEqual(Component.objects.filter(model_number="RC0603-10K").count(), 1)

    def test_create_requires_name_and_model(self):
        response = self.client.post(
            reverse("components:component_create"), self.form_data(name="", model_number="")
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("name", form.errors)
        self.assertIn("model_number", form.errors)

    def test_create_form_rejects_invalid_json_specs(self):
        response = self.client.post(
            reverse("components:component_create"),
            self.form_data(extra_specs="{not json}"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("extra_specs", response.context["form"].errors)

    def test_edit_component(self):
        response = self.client.post(
            reverse("components:component_edit", args=[self.resistor.pk]),
            self.form_data(name="贴片电阻 10kΩ 1%", model_number="RC0603-10K"),
        )
        self.assertRedirects(
            response, reverse("components:component_detail", args=[self.resistor.pk])
        )
        self.resistor.refresh_from_db()
        self.assertEqual(self.resistor.name, "贴片电阻 10kΩ 1%")
        self.assertEqual(self.resistor.storage_location, "A柜-3层-05格")

    def test_edit_page_hides_initial_stock_field(self):
        response = self.client.get(
            reverse("components:component_edit", args=[self.resistor.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("initial_stock", response.context["form"].fields)

    def test_delete_is_soft_and_hides_from_list(self):
        response = self.client.post(
            reverse("components:component_delete", args=[self.resistor.pk])
        )
        self.assertRedirects(response, reverse("components:component_list"))
        self.resistor.refresh_from_db()
        self.assertFalse(self.resistor.is_active)
        self.assertNotContains(
            self.client.get(reverse("components:component_list")), "贴片电阻 10kΩ"
        )

    # ---- 出入库 ----

    def test_stock_in_updates_quantity(self):
        response = self.client.post(
            reverse("components:component_stock", args=[self.resistor.pk]),
            {"record_type": "IN", "quantity": 15, "unit_price": "0.0100",
             "batch_number": "B2026", "storage_location": "A柜", "remark": "补货"},
        )
        self.assertRedirects(
            response, reverse("components:component_detail", args=[self.resistor.pk])
        )
        self.resistor.refresh_from_db()
        self.assertEqual(self.resistor.stock_quantity, 20)

        record = self.resistor.stock_records.get()
        self.assertEqual(record.quantity, 15)
        self.assertEqual(record.quantity_after, 20)
        self.assertEqual(record.remark, "补货")

    def test_stock_out_stores_negative_quantity(self):
        self.client.post(
            reverse("components:component_stock", args=[self.resistor.pk]),
            {"record_type": "OUT", "quantity": 3},
        )
        self.resistor.refresh_from_db()
        self.assertEqual(self.resistor.stock_quantity, 2)

        record = self.resistor.stock_records.get()
        self.assertEqual(record.quantity, -3)
        self.assertEqual(record.quantity_after, 2)

    def test_stock_out_cannot_exceed_quantity(self):
        response = self.client.post(
            reverse("components:component_stock", args=[self.resistor.pk]),
            {"record_type": "OUT", "quantity": 100},
            follow=True,
        )
        self.resistor.refresh_from_db()
        self.assertEqual(self.resistor.stock_quantity, 5)
        self.assertFalse(self.resistor.stock_records.exists())
        self.assertContains(response, "库存不足")

    def test_stock_adjust_accepts_negative_quantity(self):
        self.client.post(
            reverse("components:component_stock", args=[self.resistor.pk]),
            {"record_type": "ADJUST", "quantity": -2, "remark": "盘亏"},
        )
        self.resistor.refresh_from_db()
        self.assertEqual(self.resistor.stock_quantity, 3)
        self.assertEqual(self.resistor.stock_records.get().quantity, -2)

    def test_stock_out_rejects_negative_input(self):
        response = self.client.post(
            reverse("components:component_stock", args=[self.resistor.pk]),
            {"record_type": "OUT", "quantity": -5},
            follow=True,
        )
        self.assertContains(response, "请填写正数数量")
        self.assertFalse(self.resistor.stock_records.exists())

    def test_stock_endpoint_requires_post(self):
        response = self.client.get(
            reverse("components:component_stock", args=[self.resistor.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_create_page_renders(self):
        response = self.client.get(reverse("components:component_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新增元件")
        self.assertContains(response, 'name="initial_stock"')

    def test_delete_confirm_page_renders(self):
        response = self.client.get(
            reverse("components:component_delete", args=[self.resistor.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "确认停用")

    def test_detail_page_lists_records(self):
        StockRecord.objects.create(
            component=self.resistor, record_type=StockRecord.RecordType.IN,
            quantity=10, quantity_after=15, operator=self.user, remark="首次入库",
        )
        self.resistor.extra_specs = {"温度系数": "±100ppm"}
        self.resistor.save(update_fields=["extra_specs"])
        response = self.client.get(
            reverse("components:component_detail", args=[self.resistor.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "出入库流水")
        self.assertContains(response, "登记出入库")
        self.assertContains(response, "首次入库")
        self.assertContains(response, "温度系数")
        # 类型徽章由 {% record_type_badge %} 渲染
        self.assertContains(response, "bg-success-subtle")

