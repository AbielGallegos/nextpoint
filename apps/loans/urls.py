from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("app/materiales/<int:resource_id>/solicitar/", views.request_form, name="request"),
    path("app/prestamos/", views.mine, name="mine"),
    path("app/prestamos/<int:pk>/", views.my_detail, name="my_detail"),
    path("app/prestamos/<int:pk>/cancelar/", views.cancel, name="cancel"),
    path("panel/prestamos/", views.queue, name="queue"),
    path("panel/prestamos/<int:pk>/", views.manage_detail, name="manage_detail"),
    path("panel/prestamos/<int:pk>/<str:action>/", views.manage_action, name="manage_action"),
]
