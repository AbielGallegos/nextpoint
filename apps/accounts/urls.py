from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    path("acceso/", views.login_view, name="login"),
    path("salir/", views.logout_view, name="logout"),
    path("recuperar/", auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset.html", email_template_name="accounts/email_password_reset.txt",
        subject_template_name="accounts/email_password_reset_subject.txt", success_url=reverse_lazy("accounts:password_reset_done"),
    ), name="password_reset"),
    path("recuperar/enviado/", auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("recuperar/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="accounts/password_reset_confirm.html", success_url=reverse_lazy("accounts:password_reset_complete"),
    ), name="password_reset_confirm"),
    path("recuperar/listo/", auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
    path("invitacion/<str:token>/", views.accept_invitation, name="accept_invitation"),
    path("cuenta/", views.profile, name="profile"),
    path("cuenta/contrasena/", views.change_password, name="password_change"),
    # Panel
    path("panel/usuarios/", views.users_list, name="users"),
    path("panel/usuarios/invitar/", views.invite, name="invite"),
    path("panel/usuarios/invitaciones/<int:pk>/revocar/", views.revoke_invitation, name="revoke_invitation"),
    path("panel/usuarios/<int:pk>/", views.user_detail, name="user_detail"),
    path("panel/usuarios/<int:pk>/estado/", views.set_status, name="set_status"),
    path("panel/usuarios/<int:pk>/roles/", views.assign_role, name="assign_role"),
    path("panel/usuarios/<int:pk>/roles/<int:assignment_id>/retirar/", views.revoke_role, name="revoke_role"),
]
