"""公開の準備：ログインの失敗の制限、ヘルスチェック、CSP（architecture.md 5.5・7）。"""

import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user("owner", password="correct-horse")


def login(client, password, ip="203.0.113.1"):
    return client.post(
        "/accounts/login/",
        {"username": "owner", "password": password},
        HTTP_FLY_CLIENT_IP=ip,
    )


def test_login_works(client, owner):
    response = login(client, "correct-horse")
    assert response.status_code == 302
    assert response["Location"] == "/"


def test_lockout_after_five_failures(client, owner):
    for _ in range(5):
        login(client, "wrong")
    response = login(client, "correct-horse")
    assert response.status_code == 429
    assert "ログインを一時的に止めています" in response.content.decode()
    # 別の回線（IP アドレス）からならログインできる
    assert login(client, "correct-horse", ip="198.51.100.7").status_code == 302


def test_healthcheck_needs_no_login_or_https(client, settings):
    settings.SECURE_SSL_REDIRECT = True
    settings.ALLOWED_HOSTS = ["coffee.example.com"]
    response = client.get("/healthz", HTTP_HOST="172.19.0.2:8000")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_csp_header(client):
    csp = client.get("/accounts/login/")["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "https://fonts.googleapis.com" in csp


def test_favicon_redirect_is_public(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 301
    assert response["Location"].endswith("favicon.svg")


def test_inventory_summary_command(make_roast, product, channel):
    from io import StringIO

    from django.core.management import call_command
    from django.utils import timezone

    from inventory import services
    from inventory.models import Sale
    from inventory.services import SaleLine

    make_roast()
    services.save_sale(Sale(sold_on=timezone.localdate(), channel=channel), [SaleLine(product, 1)])
    out = StringIO()
    call_command("inventory_summary", stdout=out)
    text = out.getvalue()
    assert "焙煎記録: 1" in text
    assert "生豆の残量の合計: 4,480 g" in text
    assert "焙煎豆の残量の合計: 225 g" in text
    assert "売上の合計（税抜）: 1,700 円" in text
