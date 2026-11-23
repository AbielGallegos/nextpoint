from django.urls import path

from . import views

app_name = "learning"

urlpatterns = [
    path("app/cursos/", views.catalog, name="catalog"),
    path("app/cursos/<int:pk>/", views.detail, name="detail"),
    path("app/cursos/<int:pk>/inscribirme/", views.enroll, name="enroll"),
    path("app/lecciones/<int:pk>/", views.lesson, name="lesson"),
    path("app/lecciones/<int:pk>/completar/", views.complete, name="complete"),
    path("panel/cursos/", views.manage_list, name="manage_list"),
    path("panel/cursos/nuevo/", views.course_form, name="manage_new"),
    path("panel/cursos/<int:pk>/", views.manage_detail, name="manage_detail"),
    path("panel/cursos/<int:pk>/editar/", views.course_form, name="manage_edit"),
    path("panel/cursos/<int:pk>/lecciones/", views.add_lesson, name="add_lesson"),
    path("panel/cursos/<int:pk>/<str:action>/", views.course_action, name="action"),
]
