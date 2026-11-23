from django.urls import path

from . import views

app_name = "cases"

urlpatterns = [
    path("app/solicitudes/", views.mine, name="mine"),
    path("app/solicitudes/nueva/", views.new, name="new"),
    path("app/solicitudes/<int:pk>/", views.my_detail, name="my_detail"),
    path("app/solicitudes/<int:pk>/<str:action>/", views.my_action, name="my_action"),
    path("adjuntos/<int:pk>/", views.attachment, name="attachment"),
    path("panel/solicitudes/", views.queue, name="queue"),
    path("panel/solicitudes/<int:pk>/", views.manage_detail, name="manage_detail"),
    path("panel/solicitudes/<int:pk>/<str:action>/", views.manage_action, name="manage_action"),
]
