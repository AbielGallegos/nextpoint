from django.urls import path

from . import views

app_name = "smartmatch"

urlpatterns = [
    path("app/smartmatch/", views.home, name="home"),
    path("app/smartmatch/comparar/", views.compare, name="compare"),
    path("panel/smartmatch/", views.rules, name="rules"),
    path("panel/smartmatch/borrador/", views.save_draft, name="save_draft"),
    path("panel/smartmatch/reglas/<int:pk>/activar/", views.activate, name="activate"),
    path("panel/smartmatch/necesidades/", views.need_save, name="need_save"),
    path("panel/smartmatch/necesidades/<int:pk>/alternar/", views.need_toggle, name="need_toggle"),
]
