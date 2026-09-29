"""コーヒー豆 在庫管理アプリの設定。

秘密の値や環境ごとに変わる値は環境変数から読む（docs/architecture.md「9」）。
自分の PC では .env に書き、git には入れない。
"""

import os
from pathlib import Path

import dj_database_url
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """.env の KEY=VALUE を、まだ設定されていない環境変数にだけ入れる。"""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


DEBUG = _env_bool("DJANGO_DEBUG")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY を設定してください")
    SECRET_KEY = "django-insecure-dev-only"

ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]
if DEBUG:
    ALLOWED_HOSTS += ["localhost", "127.0.0.1"]

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "inventory",
]

MIDDLEWARE = [
    # Fly.io のヘルスチェックに、HTTPS への転送やホスト名の確認より先に答える
    "inventory.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # すべての画面をログイン必須にする（architecture.md 5.5）
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # ログインの失敗が続いたら、一時的に受け付けない（architecture.md 5.5）
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "inventory.context_processors.nav",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL（本番は Supabase の東京リージョン）。DATABASE_URL で指定する。
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default="postgres://coffee:coffee@localhost:5432/coffee",
        conn_max_age=600,
        conn_health_checks=True,
        # Supabase への接続は SSL を必須にする（architecture.md「6」）
        ssl_require=_env_bool("DATABASE_SSL_REQUIRE", not DEBUG),
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# 同じユーザー名・同じ IP アドレスで 5回続けて失敗したら、1時間受け付けない。
# 本人の端末から間違えた場合も、別の回線（スマホの通信など）からならログインできる。
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # 時間
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/lockout.html"
AXES_CLIENT_IP_CALLABLE = "inventory.middleware.client_ip"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"

# スマホで毎回ログインしなくてよいよう、90日ログインしたままにする（spec 8）
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# CSS などは WhiteNoise で配信する（architecture.md「3」）
if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# コンテンツセキュリティポリシー（architecture.md 5.5）。
# スクリプトは自分のサイトのファイルだけ。style 属性（メーターの幅など）があるので、
# スタイルは 'unsafe-inline' を許す。フォントは Google Fonts から読み込む。
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE, "https://fonts.googleapis.com"],
    "font-src": [CSP.SELF, "https://fonts.gstatic.com"],
    "img-src": [CSP.SELF, "data:"],
    "connect-src": [CSP.SELF],
    "manifest-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.NONE],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}

# ログは標準出力に出す（Fly.io の `fly logs` で見る）
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

# HTTPS はアプリの手前（Fly.io）で終わるので、そのヘッダーで判断する（architecture.md 5.5）
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = _env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # 使うドメインは fly.dev のサブドメインか、このアプリ専用のドメインなので、
    # サブドメインまで含める設定と、ブラウザの事前登録（preload）はしない
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
    SECURE_REFERRER_POLICY = "same-origin"
