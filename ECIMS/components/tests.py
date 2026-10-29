"""components 应用测试：Jinja2 模板助手 + 品类/元件管理视图。"""

from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from . import jinja2_env
from .models import Category, Component, StockRecord


def render_template(source, **context):
    """用 components 的 Jinja2 环境渲染一段模板片段，返回渲染结果。"""
    env = jinja2_env.environment(autoescape=True)
    return env.from_string(source).render(**context)


def count_action(html, title):
    """统计带指定 title 的操作按钮数，用于断言列表渲染出的行数。"""
    return html.count(f'title="{title}"')


class QuerystringFunctionTests(SimpleTestCase):
    """querystring() 保留 / 覆盖 / 移除 URL 参数。"""

    def setUp(self):
        self.request = SimpleNamespace(GET=QueryDict("q=电阻&page=2"))

    def test_keeps_existing_params(self):
        params = QueryDict(render_template("{{ querystring(page=3) }}", request=self.request))
        self.assertEqual(params["q"], "电阻")
        self.assertEqual(params["page"], "3")

    def test_empty_value_removes_param(self):
        params = QueryDict(render_template("{{ querystring(page='') }}", request=self.request))
        self.assertEqual(params["q"], "电阻")
        self.assertNotIn("page", params)

    def test_works_without_request(self):
        self.assertEqual(render_template("{{ querystring(page=1) }}"), "page=1")


class NavActiveFunctionTests(SimpleTestCase):
    """nav_active() 导航高亮，支持视图名前缀匹配。"""

    def _render(self, view_name, *names):
        request = SimpleNamespace(resolver_match=SimpleNamespace(view_name=view_name))
        source = "{{ nav_active(" + ", ".join(f"'{n}'" for n in names) + ") }}"
        return render_template(source, request=request)

    def test_prefix_match_detail_page(self):
        self.assertEqual(self._render("components:category_detail", "components:category"), "active")

    def test_exact_match(self):
        self.assertEqual(self._render("components:category_list", "components:category_list"), "active")

    def test_no_match_returns_empty(self):
        self.assertEqual(self._render("components:component_list", "components:category"), "")

    def test_missing_resolver_match(self):
        self.assertEqual(render_template("{{ nav_active('components:category') }}"), "")


class StockBadgeFunctionTests(SimpleTestCase):
    """stock_badge() 库存徽章渲染。模型实例无需入库。"""

    def test_low_stock_shows_danger_badge(self):
        component = Component(
            name="贴片电阻", model_number="RC0603-10K",
            stock_quantity=5, safety_stock=20,
        )
        html = render_template("{{ stock_badge(component) }}", component=component)
        self.assertIn("bg-danger-subtle", html)
        self.assertIn("5 个", html)
        self.assertIn('title="安全库存 20"', html)

    def test_normal_stock_shows_success_badge(self):
        component = Component(
            name="贴片电阻", model_number="RC0603-10K",
            stock_quantity=100, safety_stock=20,
        )
        html = render_template("{{ stock_badge(component) }}", component=component)
        self.assertIn("bg-success-subtle", html)
        self.assertIn("100 个", html)

    def test_without_unit(self):
        component = Component(
            name="贴片电阻", model_number="RC0603-10K",
            stock_quantity=5, safety_stock=20,
        )
        html = render_template("{{ stock_badge(component, False) }}", component=component)
        self.assertIn("5</span>", html)


class RecordTypeBadgeFunctionTests(SimpleTestCase):
    """record_type_badge() 出入库类型徽章。"""

    def test_in_badge(self):
        html = render_template("{{ record_type_badge(record) }}", record=StockRecord(record_type="IN"))
        self.assertIn("bg-success-subtle", html)
        self.assertIn("入库", html)

    def test_out_badge(self):
        html = render_template("{{ record_type_badge(record) }}", record=StockRecord(record_type="OUT"))
        self.assertIn("bg-danger-subtle", html)
        self.assertIn("出库", html)

    def test_adjust_badge(self):
        html = render_template("{{ record_type_badge(record) }}", record=StockRecord(record_type="ADJUST"))
        self.assertIn("bg-warning-subtle", html)
        self.assertIn("盘点调整", html)

    def test_unknown_type_falls_back(self):
        html = render_template("{{ record_type_badge(record) }}", record=StockRecord(record_type="XX"))
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
        html = response.content.decode()
        self.assertIn('共 <strong class="text-dark">25</strong> 条', html)
        self.assertIn("1 / 2", html)
        self.assertEqual(count_action(html, "编辑"), 20)
        # 侧边栏由 nav_active('components:category') 高亮
        self.assertIn(b"nav-link active", response.content)

    def test_second_page_has_rest_and_keeps_query(self):
        response = self.client.get(reverse("components:category_list"), {"q": "品类"})
        self.assertEqual(count_action(response.content.decode(), "编辑"), 20)

        response = self.client.get(
            reverse("components:category_list"), {"q": "品类", "page": 2}
        )
        html = response.content.decode()
        self.assertEqual(count_action(html, "编辑"), 5)
        # 分页链接由 querystring() 生成，应同时保留 q 与 page，且未被 HTML 转义
        self.assertIn("&page=1", html)
        self.assertNotIn("&amp;page=1", html)
        self.assertIn("q=", html)

    def test_invalid_page_falls_back_to_last(self):
        response = self.client.get(reverse("components:category_list"), {"page": 999})
        self.assertIn("2 / 2", response.content.decode())

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


class CategoryFormViewTests(TestCase):
    """品类新增 / 编辑 / 停用页面渲染（Jinja2 模板）。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="category-owner", password="test-pass-123"
        )
        cls.category = Category.objects.create(name="电阻", code="RES")

    def setUp(self):
        self.client.force_login(self.user)

    def test_create_page_renders(self):
        response = self.client.get(reverse("components:category_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新增品类")
        self.assertContains(response, 'name="parent"')

    def test_edit_page_renders_and_excludes_self(self):
        parent = Category.objects.create(name="被动器件", code="PAS")
        self.category.parent = parent
        self.category.save(update_fields=["parent"])

        response = self.client.get(
            reverse("components:category_edit", args=[self.category.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "编辑品类")
        self.assertContains(response, f'value="{parent.pk}"')
        self.assertNotContains(response, f'value="{self.category.pk}"')

    def test_delete_confirm_page_renders(self):
        response = self.client.get(
            reverse("components:category_delete", args=[self.category.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "确认删除")
        self.assertContains(response, "电阻")

    # ---- 类视图提交后统一 redirect() ----

    def test_create_category_redirects_to_list(self):
        response = self.client.post(
            reverse("components:category_create"),
            {"name": "电容", "code": "CAP", "description": ""},
        )
        self.assertRedirects(response, reverse("components:category_list"))
        self.assertTrue(Category.objects.filter(name="电容", code="CAP").exists())

    def test_edit_category_updates_and_redirects(self):
        response = self.client.post(
            reverse("components:category_edit", args=[self.category.pk]),
            {"name": "电阻器", "code": "RES", "description": "改名"},
        )
        self.assertRedirects(response, reverse("components:category_list"))
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "电阻器")

    def test_delete_category_is_soft_and_redirects(self):
        response = self.client.post(
            reverse("components:category_delete", args=[self.category.pk])
        )
        self.assertRedirects(response, reverse("components:category_list"))
        self.category.refresh_from_db()
        self.assertFalse(self.category.is_active)
        # 列表只展示启用中的品类
        self.assertFalse(
            Category.objects.filter(is_active=True, pk=self.category.pk).exists()
        )


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
        self.assertContains(response, '共 <strong class="text-dark">2</strong> 个元件')
        self.assertContains(response, "贴片电阻 10kΩ")
        # 低库存（5 <= 20）应渲染红色徽章
        self.assertContains(response, "bg-danger-subtle")
        self.assertContains(response, 'title="安全库存 20"')

    def test_list_search_matches_model_number(self):
        response = self.client.get(reverse("components:component_list"), {"q": "RC0603"})
        self.assertContains(response, "贴片电阻 10kΩ")
        self.assertNotContains(response, "贴片电容 100nF")

    def test_list_filters_by_parent_category(self):
        response = self.client.get(
            reverse("components:component_list"), {"category": self.root.pk}
        )
        self.assertContains(response, "贴片电阻 10kΩ")
        self.assertNotContains(response, "贴片电容 100nF")
        # 品类下拉框回填当前筛选值（filters.category == c.pk|string）
        self.assertEqual(response.content.decode().count("selected"), 1)

    def test_list_filters_low_stock_only(self):
        response = self.client.get(reverse("components:component_list"), {"low_stock": "1"})
        html = response.content.decode()
        self.assertIn('共 <strong class="text-dark">1</strong> 个元件', html)
        self.assertIn('低库存 <strong class="text-danger">1</strong> 个', html)
        self.assertNotContains(response, "贴片电容 100nF")

    def test_list_filters_mount_type(self):
        response = self.client.get(
            reverse("components:component_list"), {"mount_type": "THT"}
        )
        html = response.content.decode()
        self.assertIn('共 <strong class="text-dark">0</strong> 个元件', html)
        self.assertIn("没有符合条件的元件", html)

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
        html = response.content.decode()
        self.assertIn('共 <strong class="text-dark">25</strong> 个元件', html)
        self.assertEqual(count_action(html, "查看"), 5)
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
        # 表单 non_field_errors 由 component_form.html 渲染在 alert 中
        self.assertContains(response, "已存在")
        self.assertEqual(Component.objects.filter(model_number="RC0603-10K").count(), 1)

    def test_create_requires_name_and_model(self):
        response = self.client.post(
            reverse("components:component_create"), self.form_data(name="", model_number="")
        )
        self.assertEqual(response.status_code, 200)
        # 名称与型号两个必填错误，由 form_field 宏渲染为两条 text-danger
        html = response.content.decode()
        self.assertEqual(html.count('class="text-danger small mt-1"'), 2)
        self.assertEqual(Component.objects.count(), 2)

    def test_create_form_rejects_invalid_json_specs(self):
        response = self.client.post(
            reverse("components:component_create"),
            self.form_data(extra_specs="{not json}"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "请输入合法的 JSON")
        self.assertFalse(Component.objects.filter(model_number="RC0603-4K7").exists())

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
        self.assertNotContains(response, 'name="initial_stock"')
        self.assertContains(response, "当前库存")

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
        # {{ csrf_input }} 由 Django Jinja2 后端注入
        self.assertContains(response, "csrfmiddlewaretoken")

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
        # 类型徽章由 record_type_badge() 渲染
        self.assertContains(response, "bg-success-subtle")


class StockApplicationViewTests(TestCase):
    """入库申请 / 使用申请：类视图读取 HttpRequest，提交后 redirect() 到回执页。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="applicant", password="test-pass-123"
        )
        cls.category = Category.objects.create(name="电阻", code="RES-APP")
        cls.component = Component.objects.create(
            name="贴片电阻 1kΩ", model_number="RC0603-1K", category=cls.category,
            manufacturer="Yageo", unit="个", stock_quantity=50, safety_stock=10,
            reference_price=Decimal("0.0100"), batch_number="B-OLD",
            storage_location="A柜",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def stock_in_url(self):
        return reverse("components:stock_in_apply")

    def usage_url(self):
        return reverse("components:usage_apply")

    # ---- 导航与登录限制 ----

    def test_nav_links_point_to_application_pages(self):
        response = self.client.get(reverse("components:component_list"))
        html = response.content.decode()
        self.assertIn(f'href="{self.stock_in_url()}"', html)
        self.assertIn(f'href="{self.usage_url()}"', html)
        self.assertIn("入库申请", html)
        self.assertIn("使用申请", html)

    def test_detail_page_links_application_with_component_param(self):
        response = self.client.get(
            reverse("components:component_detail", args=[self.component.pk])
        )
        html = response.content.decode()
        self.assertIn(f'{self.stock_in_url()}?component={self.component.pk}"', html)
        self.assertIn(f'{self.usage_url()}?component={self.component.pk}"', html)

    def test_application_pages_require_login(self):
        self.client.logout()
        for url in (self.stock_in_url(), self.usage_url()):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response["Location"])

    # ---- 任务一：HttpRequest ----

    def test_stock_in_page_shows_request_info_and_prefills_from_get(self):
        response = self.client.get(
            self.stock_in_url(), {"component": self.component.pk, "quantity": 30}
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        # request.method / path / get_full_path()
        self.assertIn("request.method", html)
        self.assertIn('border-primary-subtle">GET</span>', html)
        self.assertIn("request.path", html)
        self.assertIn(self.stock_in_url(), html)
        self.assertIn("request.get_full_path()", html)
        self.assertIn(f"component={self.component.pk}&amp;quantity=30", html)

        # request.META：客户端 IP 与主机
        self.assertIn("request.META['REMOTE_ADDR']", html)
        self.assertIn("127.0.0.1", html)

        # request.GET 参数表 + 表单初始值
        self.assertIn("request.GET 查询参数", html)
        self.assertIn('value="30"', html)
        self.assertIn("贴片电阻 1kΩ", html)

    def test_usage_page_has_no_prefill_when_query_empty(self):
        response = self.client.get(self.usage_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "使用申请")
        self.assertContains(response, "使用用途")
        self.assertContains(response, "本次请求没有查询参数")
        # Cookie 尚未写入时不应出现「上次申请单号」提示
        self.assertNotContains(response, "上次使用申请单号")

    # ---- 任务二：redirect() + 回执页 ----

    def test_stock_in_post_redirects_to_result_page(self):
        response = self.client.post(
            f"{self.stock_in_url()}?component={self.component.pk}&quantity=20",
            {
                "component": self.component.pk,
                "quantity": 20,
                "unit_price": "0.0200",
                "batch_number": "B2026",
                "storage_location": "B柜-1层",
                "remark": "采购到货",
            },
        )
        self.assertEqual(response.status_code, 302)

        record = StockRecord.objects.get(
            source_type=StockRecord.SourceType.STOCK_IN_APPLY
        )
        self.assertTrue(record.apply_no.startswith("RK-"))
        self.assertEqual(record.record_type, StockRecord.RecordType.IN)
        self.assertEqual(record.quantity, 20)
        self.assertEqual(record.quantity_after, 70)
        self.assertEqual(record.unit_price, Decimal("0.0200"))
        self.assertEqual(record.batch_number, "B2026")
        self.assertEqual(record.storage_location, "B柜-1层")
        self.assertEqual(record.applicant, self.user)
        self.assertEqual(record.operator, self.user)
        self.assertEqual(record.remark, "采购到货")

        self.component.refresh_from_db()
        self.assertEqual(self.component.stock_quantity, 70)

        # 提交成功后返回 302，Location 指向回执页
        self.assertEqual(
            response.url, reverse("components:apply_result", args=[record.pk])
        )
        # set_cookie() 写入最近一次申请单号
        self.assertEqual(
            response.cookies["ecims_last_stock_in_apply"].value, record.apply_no
        )

        # 跟随重定向：回执页由 ApplyResultView 渲染
        result = self.client.get(response.url)
        self.assertEqual(result.status_code, 200)
        html = result.content.decode()
        self.assertIn("入库申请已受理", html)
        self.assertIn(record.apply_no, html)
        self.assertIn("POST-Redirect-GET", html)
        self.assertIn("302 Found", html)
        self.assertIn("本次请求信息（HttpRequest）", html)
        # 回执页本身是一次 GET 请求
        self.assertIn('border-primary-subtle">GET</span>', html)
        # 页面完整走完 base.html 的收尾标签
        self.assertTrue(html.rstrip().endswith("</html>"))

        # 横幅 → 申请单详情 → 处理流程，顺序正确
        banner_at = html.index("入库申请已受理")
        detail_at = html.index("申请单信息")
        echo_at = html.index("本次处理流程（POST-Redirect-GET）")
        self.assertLess(banner_at, detail_at)
        self.assertLess(detail_at, echo_at)

    def test_usage_post_uses_negative_quantity_and_default_price(self):
        response = self.client.post(
            self.usage_url(),
            {"component": self.component.pk, "quantity": 15, "remark": "样机调试"},
        )
        self.assertEqual(response.status_code, 302)

        record = StockRecord.objects.get(
            source_type=StockRecord.SourceType.USAGE_APPLY
        )
        self.assertTrue(record.apply_no.startswith("SY-"))
        self.assertEqual(record.record_type, StockRecord.RecordType.OUT)
        self.assertEqual(record.quantity, -15)
        self.assertEqual(record.quantity_after, 35)
        self.assertEqual(record.unit_price, Decimal("0.0000"))
        self.assertEqual(record.remark, "样机调试")

        self.component.refresh_from_db()
        self.assertEqual(self.component.stock_quantity, 35)
        self.assertEqual(
            response.cookies["ecims_last_usage_apply"].value, record.apply_no
        )
        self.assertEqual(
            response.url, reverse("components:apply_result", args=[record.pk])
        )

        # 跟随重定向，回执页由 ApplyResultView 渲染
        result = self.client.get(response.url)
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "使用申请已受理")
        self.assertContains(result, record.apply_no)

    def test_usage_rejects_insufficient_stock(self):
        response = self.client.post(
            self.usage_url(),
            {"component": self.component.pk, "quantity": 100, "remark": "超量领用"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "库存不足")
        self.assertFalse(
            StockRecord.objects.filter(
                source_type=StockRecord.SourceType.USAGE_APPLY
            ).exists()
        )
        self.component.refresh_from_db()
        self.assertEqual(self.component.stock_quantity, 50)

    def test_usage_requires_remark(self):
        response = self.client.post(
            self.usage_url(), {"component": self.component.pk, "quantity": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "这个字段是必填项。")
        self.assertFalse(StockRecord.objects.exists())

    def test_apply_result_page_requires_login_and_filters_source_type(self):
        record = StockRecord.objects.create(
            component=self.component, record_type=StockRecord.RecordType.IN,
            quantity=5, quantity_after=55, apply_no="RK-20261029-0009",
            source_type=StockRecord.SourceType.STOCK_IN_APPLY,
        )
        url = reverse("components:apply_result", args=[record.pk])

        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RK-20261029-0009")

        # 普通出入库流水（无申请来源）不在回执页展示范围
        manual = StockRecord.objects.create(
            component=self.component, record_type=StockRecord.RecordType.IN,
            quantity=1, quantity_after=56,
        )
        response = self.client.get(
            reverse("components:apply_result", args=[manual.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_apply_page_shows_last_apply_no_from_cookie(self):
        self.client.cookies["ecims_last_usage_apply"] = "SY-20261029-0007"
        response = self.client.get(self.usage_url())
        self.assertContains(response, "SY-20261029-0007")
        self.assertContains(response, "ecims_last_usage_apply")

    def test_apply_no_is_sequential_per_prefix_and_day(self):
        first = StockRecord.next_apply_no("RK")
        self.assertRegex(first, r"^RK-\d{8}-0001$")
        StockRecord.objects.create(
            component=self.component, record_type=StockRecord.RecordType.IN,
            quantity=1, quantity_after=51, apply_no=first,
        )
        self.assertTrue(StockRecord.next_apply_no("RK").endswith("-0002"))
        # 不同前缀互不影响
        self.assertTrue(StockRecord.next_apply_no("SY").endswith("-0001"))


