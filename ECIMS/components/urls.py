from django.urls import path

from . import views

app_name = "components"

urlpatterns = [
    path("", views.ComponentListView.as_view(), name="component_list"),
    path(
        "applications/stock-in/",
        views.StockInApplyView.as_view(),
        name="stock_in_apply",
    ),
    path(
        "applications/use/",
        views.UsageApplyView.as_view(),
        name="usage_apply",
    ),
    path(
        "applications/result/<int:pk>/",
        views.ApplyResultView.as_view(),
        name="apply_result",
    ),
    path("create/", views.ComponentCreateView.as_view(), name="component_create"),
    path("<int:pk>/", views.ComponentDetailView.as_view(), name="component_detail"),
    path("<int:pk>/edit/", views.ComponentUpdateView.as_view(), name="component_edit"),
    path("<int:pk>/delete/", views.ComponentDeleteView.as_view(), name="component_delete"),
    path("<int:pk>/stock/", views.ComponentStockView.as_view(), name="component_stock"),
    path("categories/", views.CategoryListView.as_view(), name="category_list"),
    path("categories/create/", views.CategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/", views.CategoryDetailView.as_view(), name="category_detail"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_edit"),
    path(
        "categories/<int:pk>/delete/",
        views.CategoryDeleteView.as_view(),
        name="category_delete",
    ),
]