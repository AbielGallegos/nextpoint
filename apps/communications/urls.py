from django.urls import path

from . import views

app_name = "communications"

urlpatterns = [
    path("app/avisos/", views.alerts, name="alerts"),
    path("app/avisos/<int:pk>/", views.alert_detail, name="alert_detail"),
    path("app/avisos/<int:pk>/leido/", views.alert_read, name="alert_read"),
    path("app/notificaciones/", views.notifications, name="notifications"),
    path("app/notificaciones/<int:pk>/abrir/", views.notification_open, name="notification_open"),
    path("app/notificaciones/marcar-todas/", views.notifications_read_all, name="notifications_read_all"),
    path("panel/avisos/", views.manage_alerts, name="manage_alerts"),
    path("panel/avisos/nuevo/", views.alert_form, name="alert_new"),
    path("panel/avisos/<int:pk>/editar/", views.alert_form, name="alert_edit"),
    path("panel/avisos/<int:pk>/publicar/", views.alert_publish, name="alert_publish"),
    path("panel/avisos/<int:pk>/retirar/", views.alert_withdraw, name="alert_withdraw"),
]
