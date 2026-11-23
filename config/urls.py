from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.loans.urls")),
    path("", include("apps.cases.urls")),
    path("", include("apps.smartmatch.urls")),
    path("", include("apps.learning.urls")),
    path("", include("apps.communications.urls")),
    path("", include("apps.reporting.urls")),
]

# El admin de Django NO se publica: toda la administración pasa por el panel con permisos de NextPoint.
handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"
