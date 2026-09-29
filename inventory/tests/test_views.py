"""画面のテスト。表示・登録・入力中の計算（htmx）を、実際のリクエストで確かめる。"""

from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from inventory import services
from inventory.models import (
    Adjustment,
    Coffee,
    GreenLot,
    Roast,
    Sale,
    Supplier,
)
from inventory.services import SaleLine

from .conftest import choice

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(client):
    user = get_user_model().objects.create_user("owner", password="pw-for-tests")
    client.force_login(user)
    return user


def body(response) -> str:
    return response.content.decode()


def roast_post(lot, coffee, **overrides):
    data = {
        "idempotency_key": str(uuid4()),
        "green_lot": lot.pk,
        "coffee_choice": coffee.pk if coffee else "",
        "roasted_at": "2026-09-10T10:00",
        "roaster": "手回し焙煎機",
        "input_g": "500",
        "handpick_g": "20",
        "output_g": "425",
        "duration_m": "10",
        "duration_sec": "30",
        "first_m": "8",
        "first_sec": "30",
        "roast_level": "high",
        "rating": "",
    }
    data.update(overrides)
    return data


def sale_post(channel, rows, **overrides):
    data = {
        "idempotency_key": str(uuid4()),
        "sold_on": timezone.localdate().isoformat(),
        "channel": channel.pk,
        "items-TOTAL_FORMS": str(len(rows)),
        "items-INITIAL_FORMS": "0",
        "items-MIN_NUM_FORMS": "0",
        "items-MAX_NUM_FORMS": "1000",
    }
    for i, (product, qty, price) in enumerate(rows):
        data[f"items-{i}-product"] = product.pk if product else ""
        data[f"items-{i}-quantity"] = qty
        data[f"items-{i}-unit_price_yen"] = price
        data[f"items-{i}-prev_product"] = product.pk if product else ""
    data.update(overrides)
    return data


# --- ログイン -------------------------------------------------------------------


def test_pages_require_login(client):
    for url in ["/", "/lots/", "/roasts/new/", "/sales/", "/reports/"]:
        response = client.get(url)
        assert response.status_code == 302
        assert response["Location"].startswith("/accounts/login/")


def test_login_page_is_public(client):
    assert client.get("/accounts/login/").status_code == 200


# --- すべての画面が表示できる ------------------------------------------------------


def test_every_screen_renders(client, owner, make_roast, product, channel, tasting_reason):
    roast = make_roast()
    lot = roast.green_lot
    sale = services.save_sale(
        Sale(sold_on=timezone.localdate(), channel=channel), [SaleLine(product, 1)]
    )
    services.save_adjustment(Adjustment(roast=roast, delta_g=-5, reason=tasting_reason))
    urls = [
        "/",
        "/menu/",
        "/lots/",
        "/lots/?f=empty",
        "/lots/?f=all&q=コロンビア",
        f"/lots/{lot.pk}/",
        "/lots/new/",
        f"/lots/new/?copy={lot.pk}",
        f"/lots/{lot.pk}/edit/",
        "/roasts/",
        f"/roasts/?lot={lot.pk}&coffee={roast.coffee_id}",
        f"/roasts/{roast.pk}/",
        "/roasts/new/",
        f"/roasts/{roast.pk}/edit/",
        "/coffees/",
        "/coffees/?show=all",
        "/sales/",
        "/sales/?month=all",
        f"/sales/{sale.pk}/",
        "/sales/new/",
        f"/sales/{sale.pk}/edit/",
        "/adjust/",
        f"/adjust/?target=roast:{roast.pk}",
        f"/adjust/?target=lot:{lot.pk}",
        "/reports/",
        "/reports/?period=all",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, url


def test_home_shows_spec_example(client, owner, make_roast, product, channel):
    """仕様書 5 の計算例：今月 1,700円を売って、粗利 1,161円（68.3%）。"""
    make_roast()
    services.save_sale(Sale(sold_on=timezone.localdate(), channel=channel), [SaleLine(product, 1)])
    html = body(client.get("/"))
    assert "¥1,700" in html
    assert "¥1,161" in html
    assert "68.3%" in html
    assert "225 g" in html  # 焙煎豆の残量
    assert "200g×1" in html  # 何個分
    assert "4.48 kg" in html  # 生豆の残量


# --- 生豆ロット -----------------------------------------------------------------


def lot_post(**overrides):
    data = {
        "name": "エチオピア ゲデオ 2026-09",
        "purchased_on": "2026-09-01",
        "supplier_choice": "__new__",
        "new_supplier": "みどり生豆店",
        "country": "エチオピア",
        "weight_kg": "５",
        "price_yen": "12,500",
        "extra_cost_yen": "1200",
        "certifications": [choice("certification", "有機JAS").pk],
    }
    data.update(overrides)
    return data


def test_lot_create_with_new_supplier(client, owner):
    response = client.post("/lots/new/", lot_post())
    lot = GreenLot.objects.get()
    assert response.status_code == 302
    assert response["Location"] == f"/lots/{lot.pk}/"
    assert lot.weight_g == 5000  # 全角の「５」kg
    assert lot.price_yen == 12500  # 桁区切りのカンマ
    assert lot.supplier.name == "みどり生豆店"
    assert [c.label for c in lot.certifications.all()] == ["有機JAS"]


def test_lot_form_errors_are_shown(client, owner):
    response = client.post("/lots/new/", lot_post(new_supplier="", country="", weight_kg="abc"))
    html = body(response)
    assert response.status_code == 200
    assert "保存できません" in html
    assert "新しい問屋の名前を入力してください。" in html
    assert not GreenLot.objects.exists()
    assert not Supplier.objects.exists()


def test_lot_weight_cannot_go_below_used(client, owner, lot, make_roast):
    make_roast()  # 520g 使った
    data = lot_post(supplier_choice=str(lot.supplier_id), weight_kg="0.5", name=lot.name)
    html = body(client.post(f"/lots/{lot.pk}/edit/", data))
    assert "残量が -20g になります" in html
    assert GreenLot.objects.get(pk=lot.pk).weight_g == 5000


def test_lot_preview_kg_price(client, owner):
    html = body(
        client.post(
            "/lots/preview/", {"weight_kg": "5", "price_yen": "9000", "extra_cost_yen": "1000"}
        )
    )
    assert "¥2,000/kg" in html
    assert "2.00 円/g" in html


def test_lot_copy_prefills_origin(client, owner, lot):
    lot.farm = "ラ・エスペランサ農園"
    lot.memo = "棚の上"
    lot.save()
    html = body(client.get(f"/lots/new/?copy={lot.pk}"))
    assert "ラ・エスペランサ農園" in html
    assert "棚の上" not in html


def test_unused_lot_can_be_deleted(client, owner, lot):
    response = client.post(f"/lots/{lot.pk}/delete/")
    assert response["Location"] == "/lots/"
    assert not GreenLot.objects.exists()


# --- 焙煎記録 -------------------------------------------------------------------


def test_roast_create(client, owner, lot, coffee):
    response = client.post("/roasts/new/", roast_post(lot, coffee))
    roast = Roast.objects.get()
    assert response["Location"] == f"/roasts/{roast.pk}/"
    assert (roast.duration_s, roast.first_crack_s, roast.second_crack_s) == (630, 510, None)
    assert roast.roast_level == "high"
    assert lot.remaining() == 4480
    html = body(client.get(response["Location"]))
    assert "の在庫が 425 g 増えました" in html
    assert "2.45 円/g" in html


def test_roast_double_submit_saves_once(client, owner, lot, coffee):
    data = roast_post(lot, coffee)
    client.post("/roasts/new/", data)
    client.post("/roasts/new/", data)
    assert Roast.objects.count() == 1


def test_roast_new_coffee_inline(client, owner, lot):
    data = roast_post(lot, None, coffee_choice="__new__", new_coffee="ブラジル 深煎り")
    client.post("/roasts/new/", data)
    assert Roast.objects.get().coffee.name == "ブラジル 深煎り"


def test_roast_loss_rate_needs_confirmation(client, owner, lot, coffee):
    data = roast_post(lot, coffee, output_g="480")  # ロス率 4%
    html = body(client.post("/roasts/new/", data))
    assert "ロス率が 4.0% です" in html
    assert not Roast.objects.exists()
    data["confirm_loss"] = "1"
    assert client.post("/roasts/new/", data).status_code == 302
    assert Roast.objects.count() == 1


def test_roast_validation_messages(client, owner, lot, coffee):
    data = roast_post(lot, coffee, duration_m="", duration_sec="", first_m="9", first_sec="75")
    html = body(client.post("/roasts/new/", data))
    assert "焙煎時間（投入から排出まで）を入力してください。" in html
    assert "1ハゼ開始は、分と秒を整数で入力してください（秒は 0〜59）。" in html
    html = body(client.post("/roasts/new/", roast_post(lot, coffee, output_g="500")))
    assert "焙煎後重量は、投入量より少なくしてください。" in html


def test_roast_over_lot_stock_shows_error(client, owner, make_lot, coffee):
    small = make_lot(weight_g=500)
    html = body(client.post("/roasts/new/", roast_post(small, coffee)))
    assert "生豆ロットの残量が足りません" in html
    assert not Roast.objects.exists()


def test_roast_edit_keeps_coffee_after_sale(client, owner, make_roast, product, channel):
    roast = make_roast()
    services.save_sale(Sale(sold_on=date(2026, 9, 20), channel=channel), [SaleLine(product, 1)])
    other = Coffee.objects.create(name="別の銘柄")
    data = roast_post(roast.green_lot, other, tasting_notes="オレンジ", rating="4")
    response = client.post(f"/roasts/{roast.pk}/edit/", data)
    assert response.status_code == 302
    roast.refresh_from_db()
    assert roast.coffee_id == product.coffee_id  # 送られてきた銘柄は使わない
    assert (roast.tasting_notes, roast.rating) == ("オレンジ", 4)


def test_roast_preview_numbers_and_preset(client, owner, make_roast, lot):
    make_roast(roast_level="city")
    data = roast_post(lot, None, lot_changed="1")
    html = body(client.post("/roasts/preview/", data))
    assert "15.0%" in html  # ロス率
    assert "2.45 円/g" in html
    assert "19.0%" in html  # DTR
    assert "残り 4,480 g" in html
    assert 'value="city" checked' in html  # 前回の焙煎度


# --- 銘柄・商品 -----------------------------------------------------------------


def test_coffee_and_product_management(client, owner):
    client.post("/coffees/new/", {"name": "ケニア 浅煎り"})
    coffee = Coffee.objects.get(name="ケニア 浅煎り")
    client.post(f"/coffees/{coffee.pk}/products/new/", {"weight_g": "100", "price_yen": "1,100"})
    product = coffee.products.get()
    assert (product.weight_g, product.price_yen, product.packaging_cost_yen) == (100, 1100, 0)
    client.post(f"/products/{product.pk}/toggle/")
    client.post(f"/coffees/{coffee.pk}/toggle/")
    product.refresh_from_db()
    coffee.refresh_from_db()
    assert not product.is_active and not coffee.is_active


# --- 販売 -----------------------------------------------------------------------


def test_sale_create(client, owner, make_roast, product, channel):
    make_roast()
    response = client.post("/sales/new/", sale_post(channel, [(product, "1", "1700")]))
    sale = Sale.objects.get()
    assert response["Location"] == f"/sales/{sale.pk}/"
    html = body(client.get(response["Location"]))
    assert "販売を記録しました（¥1,700）" in html
    assert "¥539" in html and "¥1,161" in html and "68.3%" in html


def test_sale_blank_price_uses_product_price(client, owner, make_roast, product, channel):
    make_roast()
    client.post("/sales/new/", sale_post(channel, [(product, "2", "")]))
    assert Sale.objects.get().amount_yen == 3400


def test_sale_short_stock_shows_error(client, owner, make_roast, product, channel):
    make_roast()  # 425g
    html = body(client.post("/sales/new/", sale_post(channel, [(product, "3", "1700")])))
    assert "在庫が 175 g 足りません" in html
    assert not Sale.objects.exists()


def test_sale_needs_a_product(client, owner, channel):
    html = body(client.post("/sales/new/", sale_post(channel, [(None, "1", "")])))
    assert "商品を 1 つ以上選んでください。" in html


def test_sale_edit_and_delete(client, owner, make_roast, product, channel):
    roast = make_roast()
    client.post("/sales/new/", sale_post(channel, [(product, "1", "1700")]))
    sale = Sale.objects.get()
    client.post(f"/sales/{sale.pk}/edit/", sale_post(channel, [(product, "2", "1500")]))
    assert Sale.objects.get().amount_yen == 3000
    assert roast.remaining() == 25
    client.post(f"/sales/{sale.pk}/delete/")
    assert roast.remaining() == 425


def test_sale_preview(client, owner, make_roast, product, channel):
    make_roast()
    data = sale_post(channel, [(product, "3", "1700")])
    html = body(client.post("/sales/preview/", data))
    assert "175 g 足りません" in html
    assert "¥5,100" in html
    # 行を足す
    html = body(client.post("/sales/preview/", {**data, "action": "add"}))
    assert 'name="items-TOTAL_FORMS" value="2"' in html
    # 商品を選び直すと、単価が販売価格になる
    changed = {
        **data,
        "items-0-prev_product": "",
        "items-0-unit_price_yen": "",
        "action": "product",
    }
    html = body(client.post("/sales/preview/", changed))
    assert 'name="items-0-unit_price_yen" value="1700"' in html
    # 行を消す
    html = body(client.post("/sales/preview/", {**data, "action": "remove:0"}))
    assert 'name="items-TOTAL_FORMS" value="1"' in html
    assert 'name="items-0-product"' in html


# --- 在庫調整 -------------------------------------------------------------------


def adjust_post(target, **overrides):
    data = {
        "idempotency_key": str(uuid4()),
        "target": target,
        "mode": "delta",
        "delta_g": "",
        "actual_g": "",
        "adjusted_on": "2026-09-11",
        "reason": choice("adjustment_reason", "試飲・自家用").pk,
        "memo": "",
    }
    data.update(overrides)
    return data


def test_adjust_delta_and_stocktake(client, owner, make_roast):
    roast = make_roast()
    response = client.post("/adjust/", adjust_post(f"roast:{roast.pk}", delta_g="-25"))
    assert response["Location"] == f"/roasts/{roast.pk}/"
    assert roast.remaining() == 400
    lot = roast.green_lot
    client.post("/adjust/", adjust_post(f"lot:{lot.pk}", mode="count", actual_g="4,450"))
    assert lot.remaining() == 4450
    html = body(
        client.post("/adjust/", adjust_post(f"lot:{lot.pk}", mode="count", actual_g="4450"))
    )
    assert "調整はいりません" in html


def test_adjust_cannot_go_negative(client, owner, make_roast):
    roast = make_roast()
    html = body(client.post("/adjust/", adjust_post(f"roast:{roast.pk}", delta_g="-500")))
    assert "残量が -75g になります" in html
    assert not Adjustment.objects.exists()


def test_adjust_preview_and_delete(client, owner, make_roast):
    roast = make_roast()
    html = body(
        client.post(
            "/adjust/preview/", {"target": f"roast:{roast.pk}", "mode": "count", "actual_g": "400"}
        )
    )
    assert "425 g" in html and "−25 g" in html and "400 g" in html
    client.post("/adjust/", adjust_post(f"roast:{roast.pk}", delta_g="-25"))
    adjustment = Adjustment.objects.get()
    client.post(f"/adjust/{adjustment.pk}/delete/")
    assert not Adjustment.objects.exists()


# --- 集計 -----------------------------------------------------------------------


def test_report_totals(client, owner, make_roast, product, channel):
    make_roast()
    today = timezone.localdate()
    services.save_sale(Sale(sold_on=today, channel=channel), [SaleLine(product, 1)])
    html = body(client.get("/reports/?period=this"))
    assert f"{today.year}年{today.month}月" in html
    assert "¥1,700" in html and "¥1,161" in html and "68.3%" in html
    assert "0.20 kg" in html  # 販売した重さ
    assert product.coffee.name in html


# --- 管理画面 -------------------------------------------------------------------


def test_admin_shows_stock_error_instead_of_crashing(client, make_lot, coffee):
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
    assert "生豆ロットの残量が足りません" in body(response)
    assert not Roast.objects.exists()
