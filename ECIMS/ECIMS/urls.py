"""
URL configuration for ECIMS project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    # 应用命名空间：components/urls.py 里的 app_name = "components"
    # 实例命名空间：这里的 namespace="components"    
    path("components/", include(("components.urls", "components"), namespace="components")),
    # 测试版实例
    path("demo/components/",include(("components.urls", "components"), namespace="test"),),
]
