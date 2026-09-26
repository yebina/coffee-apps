import os

from django.contrib import admin
from django.urls import include, path

# 管理画面の URL は推測されにくいものにする（architecture.md 5.5）
ADMIN_PATH = os.environ.get("DJANGO_ADMIN_PATH", "admin/")

urlpatterns = [
    path(ADMIN_PATH, admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("inventory.urls")),
]
