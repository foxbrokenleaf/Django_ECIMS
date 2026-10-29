"""accounts 应用视图：代码创建用户、登录 / 退出与登录访问限制。

- 任务一：user_create() 调用 create_user()，superuser_create() 调用 create_superuser()
- 任务二：login_view() 用 authenticate() + login()，logout_view() 用 logout()
- 任务三：@login_required 限制访问，LOGIN_URL 在 settings.py 中统一配置
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import LoginForm, UserCreateForm

User = get_user_model()


def _safe_next_url(request):
    """读取并校验 next 参数，只允许站内地址，避免开放重定向。"""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ""


# ------------------------------------------------------------ 任务一：创建用户


def user_create(request):
    """创建普通用户：演示 User.objects.create_user()。"""

    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
            )
            messages.success(request, f"普通用户「{user.username}」创建成功，请登录。")
            if request.user.is_authenticated:
                return redirect("accounts:dashboard")
            return redirect("accounts:login")
    else:
        form = UserCreateForm()

    return render(request, "accounts/user_form.html", {"form": form, "mode": "user"})


@login_required(login_url="accounts:login")
def superuser_create(request):
    """创建超级用户：演示 User.objects.create_superuser()。

    超级用户拥有全部权限，因此该视图只允许已登录的超级用户访问；
    第一个超级用户请使用 ``python manage.py createsuperuser`` 创建。
    """

    if not request.user.is_superuser:
        raise PermissionDenied("只有超级用户可以创建超级用户。")

    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = User.objects.create_superuser(
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
            )
            messages.success(request, f"超级用户「{user.username}」创建成功。")
            return redirect("accounts:dashboard")
    else:
        form = UserCreateForm()

    return render(request, "accounts/user_form.html", {"form": form, "mode": "superuser"})


# ------------------------------------------------------------ 任务二：登录与退出


def login_view(request):
    """登录视图：authenticate() 校验身份，login() 把登录状态写入 Session。"""

    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    next_url = _safe_next_url(request)

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            user = authenticate(
                request,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            if user is None:
                messages.error(request, "用户名或密码错误，请重新输入。")
            else:
                login(request, user)  # 登录状态写入 Session
                messages.success(request, f"欢迎回来，{user.username}！")
                return redirect(next_url or settings.LOGIN_REDIRECT_URL)
    else:
        form = LoginForm()

    return render(request, "accounts/login.html", {"form": form, "next": next_url})


@require_POST
def logout_view(request):
    """退出视图：logout() 会清空当前 Session。

    Django 5 不再允许通过 GET 退出（避免浏览器预取导致误退出），
    因此这里用 @require_POST 限制，模板中必须使用 POST 表单提交。
    """

    logout(request)
    messages.success(request, "已退出登录。")
    return redirect("accounts:login")


# ---------------------------------------------------- 任务三：登录后才能访问的页面


@login_required(login_url="accounts:login")
def dashboard(request):
    """个人中心：未登录时会被重定向到 accounts:login 并带上 next 参数。"""

    managed_users = []
    if request.user.is_superuser:
        managed_users = User.objects.order_by("-date_joined")[:10]

    return render(request, "accounts/dashboard.html", {
        "managed_users": managed_users,
        "user_count": User.objects.count(),
    })
