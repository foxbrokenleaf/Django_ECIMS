"""accounts 应用路由：用户创建、登录、退出与个人中心。"""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("users/create/", views.user_create, name="user_create"),
    path("users/create-superuser/", views.superuser_create, name="superuser_create"),
]
