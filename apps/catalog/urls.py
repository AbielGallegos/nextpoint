from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("app/materiales/", views.catalog_list, name="list"),
    path("app/materiales/<int:pk>/", views.catalog_detail, name="detail"),
    path("panel/recursos/", views.manage_list, name="manage_list"),
    path("panel/recursos/nuevo/", views.manage_form, name="manage_new"),
    path("panel/recursos/categorias/", views.categories, name="categories"),
    path("panel/recursos/<int:pk>/", views.manage_detail, name="manage_detail"),
    path("panel/recursos/<int:pk>/editar/", views.manage_form, name="manage_edit"),
    path("panel/recursos/<int:pk>/ejemplares/", views.add_unit, name="add_unit"),
    path("panel/recursos/<int:pk>/ejemplares/<int:unit_id>/estado/", views.unit_state, name="unit_state"),
]
