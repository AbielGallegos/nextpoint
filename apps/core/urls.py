from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("acerca/", views.about, name="about"),
    path("ayuda/", views.help_center, name="help"),
    path("inicio/", views.home_redirect, name="home_redirect"),
    path("health", views.health, name="health"),
    path("app/", views.student_home, name="student_home"),
    path("app/ayuda/", views.support_mine, name="support_mine"),
    path("app/ayuda/tickets/<int:pk>/", views.support_detail, name="support_detail"),
    path("panel/soporte/", views.support_queue, name="support_queue"),
    path("panel/tecnico/", views.tech, name="tech"),
    path("panel/configuracion/", views.policies, name="policies"),
]
