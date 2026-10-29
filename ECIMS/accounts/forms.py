"""accounts 应用表单：登录与用户创建。

表单只负责校验输入，真正的用户落库在视图中调用
``User.objects.create_user()`` / ``User.objects.create_superuser()`` 完成。
"""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class BootstrapFormMixin:
    """给所有字段自动加上 Bootstrap 样式，保持与 components 表单风格一致。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


class LoginForm(BootstrapFormMixin, forms.Form):
    """登录表单：只收集用户名与密码，认证交给 authenticate()。"""

    username = forms.CharField(
        label="用户名",
        max_length=150,
        widget=forms.TextInput(attrs={
            "autofocus": True,
            "autocomplete": "username",
            "placeholder": "请输入用户名",
        }),
    )
    password = forms.CharField(
        label="密码",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "current-password",
            "placeholder": "请输入密码",
        }),
    )


class UserCreateForm(BootstrapFormMixin, forms.Form):
    """创建用户表单，普通用户与超级用户共用。"""

    username = forms.CharField(
        label="用户名",
        max_length=150,
        help_text="150 个字符以内，可使用字母、数字和 @/./+/-/_",
    )
    email = forms.EmailField(label="邮箱", required=False)
    password1 = forms.CharField(
        label="密码",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="确认密码",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("该用户名已被占用，请更换一个。")
        return username

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "两次输入的密码不一致。")

        if password1:
            try:
                validate_password(password1)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned
