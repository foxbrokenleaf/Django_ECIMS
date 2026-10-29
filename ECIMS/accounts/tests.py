"""accounts 应用测试：代码创建用户、登录 / 退出与 @login_required 访问限制。"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

# 满足默认密码校验器（长度 / 常见密码 / 纯数字）的测试密码
PASSWORD = "Eq8#kLm2nPq7"
FORM_DATA = {
    "username": "zhangsan",
    "email": "zhangsan@example.com",
    "password1": PASSWORD,
    "password2": PASSWORD,
}


class UserCreateViewTests(TestCase):
    """任务一：普通用户通过 create_user() 创建。"""

    def test_get_renders_form_with_csrf(self):
        response = self.client.get(reverse("accounts:user_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="password2"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_post_creates_normal_user(self):
        response = self.client.post(reverse("accounts:user_create"), FORM_DATA)

        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(username="zhangsan")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(user.email, "zhangsan@example.com")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_password_mismatch_does_not_create_user(self):
        data = {**FORM_DATA, "password2": PASSWORD + "x"}
        response = self.client.post(reverse("accounts:user_create"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "两次输入的密码不一致")
        self.assertFalse(User.objects.filter(username="zhangsan").exists())

    def test_duplicate_username_rejected(self):
        User.objects.create_user("zhangsan", password=PASSWORD)
        response = self.client.post(reverse("accounts:user_create"), FORM_DATA)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "该用户名已被占用")
        self.assertEqual(User.objects.filter(username="zhangsan").count(), 1)

    def test_weak_password_rejected_by_validators(self):
        data = {**FORM_DATA, "password1": "12345678", "password2": "12345678"}
        response = self.client.post(reverse("accounts:user_create"), data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="zhangsan").exists())


class SuperuserCreateViewTests(TestCase):
    """任务一：超级用户通过 create_superuser() 创建，且仅超级用户可操作。"""

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        cls.member = User.objects.create_user("member", password=PASSWORD)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("accounts:superuser_create"))
        expected = f"{reverse('accounts:login')}?next={reverse('accounts:superuser_create')}"
        self.assertRedirects(response, expected)

    def test_normal_user_forbidden(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("accounts:superuser_create"))
        self.assertEqual(response.status_code, 403)

    def test_normal_user_cannot_post(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("accounts:superuser_create"), {
            **FORM_DATA, "username": "hacker",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="hacker").exists())

    def test_superuser_creates_superuser(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse("accounts:superuser_create"), {
            **FORM_DATA, "username": "admin2",
        })

        self.assertRedirects(response, reverse("accounts:dashboard"))
        user = User.objects.get(username="admin2")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_superuser_form_renders(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse("accounts:superuser_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "创建超级用户")
        self.assertContains(response, "csrfmiddlewaretoken")


class LoginViewTests(TestCase):
    """任务二：authenticate() 校验 + login() 写入 Session。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("lisi", password=PASSWORD)

    def test_get_renders_login_form_with_csrf(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_login_success_writes_session(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "lisi", "password": PASSWORD,
        })

        self.assertRedirects(response, settings.LOGIN_REDIRECT_URL)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_login_failure_shows_error(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "lisi", "password": "wrong-password"},
            follow=True,
        )

        self.assertContains(response, "用户名或密码错误")
        # messages.error 被映射为 Bootstrap 的 danger 样式
        self.assertContains(response, "alert-danger")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_honors_next_parameter(self):
        dashboard_url = reverse("accounts:dashboard")
        response = self.client.post(
            f"{reverse('accounts:login')}?next={dashboard_url}",
            {"username": "lisi", "password": PASSWORD},
        )

        self.assertRedirects(response, dashboard_url)

    def test_external_next_is_ignored(self):
        response = self.client.post(
            f"{reverse('accounts:login')}?next=https://evil.example.com/",
            {"username": "lisi", "password": PASSWORD},
        )

        self.assertRedirects(response, settings.LOGIN_REDIRECT_URL)

    def test_authenticated_user_redirected_to_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:login"))
        self.assertRedirects(response, reverse("accounts:dashboard"))


class LogoutViewTests(TestCase):
    """任务二：logout() 清除 Session，且只接受 POST。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("wangwu", password=PASSWORD)

    def setUp(self):
        self.client.force_login(self.user)

    def test_post_logout_clears_session(self):
        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_get_logout_not_allowed(self):
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)


class LoginRequiredTests(TestCase):
    """任务三：@login_required + LOGIN_URL 的跳转行为。"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("zhaoliu", password=PASSWORD)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("accounts:dashboard"))
        expected = f"{reverse('accounts:login')}?next={reverse('accounts:dashboard')}"
        self.assertRedirects(response, expected)

    def test_existing_component_views_use_settings_login_url(self):
        response = self.client.get(reverse("components:component_list"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))
        self.assertIn(reverse("components:component_list"), response["Location"])

    def test_dashboard_renders_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "个人中心")
        self.assertContains(response, "zhaoliu")
        # 普通用户看不到“创建超级用户”入口
        self.assertNotContains(response, "创建超级用户")

    def test_superuser_dashboard_shows_management_entry(self):
        root = User.objects.create_superuser("superroot", "root@example.com", PASSWORD)
        self.client.force_login(root)
        response = self.client.get(reverse("accounts:dashboard"))

        self.assertContains(response, "创建超级用户")
        self.assertContains(response, "最近注册的用户")
        self.assertContains(response, f"共 {User.objects.count()} 个账号")
