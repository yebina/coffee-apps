import os

from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

# 管理画面の URL は推測されにくいものにする（architecture.md 5.5）
ADMIN_PATH = os.environ.get("DJANGO_ADMIN_PATH", "admin/")

urlpatterns = [
    path(ADMIN_PATH, admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("inventory.urls")),
    path(
        "favicon.ico",
        login_not_required(RedirectView.as_view(url=static("favicon.svg"), permanent=True)),
    ),
]
