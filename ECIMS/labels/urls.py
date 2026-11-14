"""labels 应用路由。"""

from django.urls import path

from . import views

app_name = "labels"

urlpatterns = [
    path("", views.home, name="home"),
    path("export/components/", views.export_components, name="export_components"),
    path("print/", views.label_print, name="print"),
    path("printers/", views.printer_status, name="printers"),
    path("history/", views.label_history, name="history"),
    path("history/export/", views.export_history, name="export_history"),
    path("templates/", views.template_list, name="template_list"),
    path("templates/new/", views.template_create, name="template_create"),
    path("templates/<int:pk>/edit/", views.template_edit, name="template_edit"),
    path("templates/<int:pk>/toggle/", views.template_toggle, name="template_toggle"),
    path("preview/<int:pk>/", views.label_preview, name="preview"),
    path("scan/<uuid:uid>/", views.scan_component, name="scan"),
]
