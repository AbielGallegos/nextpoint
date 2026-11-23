from django.urls import path

from . import views

app_name = "reporting"

urlpatterns = [
    path("panel/", views.panel_home, name="panel_home"),
    path("panel/informes/", views.reports, name="reports"),
    path("panel/informes/exportar/", views.export, name="export"),
    path("panel/auditoria/", views.audit, name="audit"),
    path("api/v1/me", views.api_me, name="api_me"),
    path("api/v1/admin/kpis", views.api_admin_kpis, name="api_admin_kpis"),
]
