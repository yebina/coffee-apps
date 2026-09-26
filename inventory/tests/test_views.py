import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


def test_home_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


def test_login_page_is_public(client):
    assert client.get("/accounts/login/").status_code == 200


def test_home_after_login(client, make_roast):
    make_roast()
    user = get_user_model().objects.create_user("owner", password="pw-for-tests")
    client.force_login(user)
    response = client.get("/")
    assert response.status_code == 200
    assert "425g" in response.content.decode()
    assert "4480g" in response.content.decode()


def test_admin_shows_stock_error_instead_of_crashing(client, make_lot, coffee):
    from inventory.models import Roast

    lot = make_lot(weight_g=500)
    admin = get_user_model().objects.create_superuser("admin", password="pw-for-tests")
    client.force_login(admin)
    response = client.post(
        "/admin/inventory/roast/add/",
        {
            "roasted_at_0": "2026-09-10",
            "roasted_at_1": "10:00:00",
            "green_lot": lot.pk,
            "coffee": coffee.pk,
            "roaster": "手回し焙煎機",
            "input_g": 600,
            "handpick_g": 0,
            "output_g": 500,
            "duration_s": 630,
        },
        follow=True,
    )
    assert response.status_code == 200
    assert "生豆ロットの残量が足りません" in response.content.decode()
    assert not Roast.objects.exists()
