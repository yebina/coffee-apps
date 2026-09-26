"""在庫を動かす処理と、仕様書「6. 入力チェックと業務ルール」。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from inventory import calc, services
from inventory.models import (
    Adjustment,
    Allocation,
    Coffee,
    GreenLot,
    Product,
    Roast,
    Sale,
)
from inventory.services import SaleLine, StockError

from .conftest import JST

pytestmark = pytest.mark.django_db


def sell(channel, *lines, sale=None, key=None):
    sale = sale or Sale(sold_on=date(2026, 9, 20), channel=channel)
    return services.save_sale(sale, [SaleLine(p, q) for p, q in lines], idempotency_key=key)


# --- 仕様書 5 の計算例を DB で通す ---------------------------------------------


def test_spec_example_end_to_end(lot, make_roast, product, channel):
    roast = make_roast()
    sale = sell(channel, (product, 1))

    assert lot.remaining() == 4480
    assert roast.remaining() == 225
    assert product.coffee.remaining() == 225

    lot = GreenLot.objects.get(pk=lot.pk)
    assert lot.price_per_kg == 2000
    roast = Roast.objects.get(pk=roast.pk)
    assert calc.display_per_g(roast.cost_per_g) == Decimal("2.45")
    assert calc.display_percent(roast.loss_rate) == Decimal("15.0")

    sale = Sale.objects.get(pk=sale.pk)
    assert sale.amount_yen == 1700
    assert calc.display_yen(sale.cost_yen) == 539
    assert calc.display_yen(sale.gross_profit_yen) == 1161


# --- 焙煎記録 -------------------------------------------------------------------


def test_roast_cannot_use_more_than_lot_remaining(make_lot, make_roast):
    small = make_lot(weight_g=500)
    with pytest.raises(StockError, match="生豆ロットの残量が足りません"):
        make_roast(green_lot=small, input_g=490, handpick_g=20, output_g=420)
    assert not Roast.objects.exists()


def test_roast_output_must_be_less_than_input(make_roast):
    with pytest.raises(ValidationError):
        make_roast(input_g=500, output_g=500)


@pytest.mark.parametrize(
    ("first", "second", "duration"),
    [(600, None, 600), (None, 630, 630), (540, 500, 630), (540, 540, 630)],
)
def test_roast_crack_times_must_be_in_order(make_roast, first, second, duration):
    with pytest.raises(ValidationError):
        make_roast(first_crack_s=first, second_crack_s=second, duration_s=duration)


def test_roast_edit_gives_back_old_usage(make_lot, make_roast):
    lot = make_lot(weight_g=1000)
    roast = make_roast(green_lot=lot, input_g=900, handpick_g=0, output_g=770)
    roast.input_g = 950  # 使える量は 100 + 900
    roast.output_g = 800
    services.save_roast(roast)
    assert lot.remaining() == 50


def test_roast_move_to_another_lot(make_lot, make_roast):
    a = make_lot(name="A")
    b = make_lot(name="B")
    roast = make_roast(green_lot=a)
    roast.green_lot = b
    services.save_roast(roast)
    assert a.remaining() == 5000
    assert b.remaining() == 4480


def test_roast_output_cannot_go_below_used(make_roast, product, channel):
    roast = make_roast()
    sell(channel, (product, 1))
    roast.output_g = 150
    with pytest.raises(StockError, match="すでに 200g"):
        services.save_roast(roast)


def test_roast_coffee_cannot_change_after_sale(make_roast, product, channel):
    roast = make_roast()
    sell(channel, (product, 1))
    roast.coffee = Coffee.objects.create(name="別の銘柄")
    with pytest.raises(StockError, match="銘柄を変えられません"):
        services.save_roast(roast)


def test_used_roast_cannot_be_deleted(make_roast, product, channel):
    roast = make_roast()
    sell(channel, (product, 1))
    with pytest.raises(StockError):
        services.delete_roast(roast)


def test_unused_roast_can_be_deleted(lot, make_roast):
    roast = make_roast()
    services.delete_roast(roast)
    assert lot.remaining() == 5000


def test_roast_idempotency(make_roast):
    key = uuid4()
    first = make_roast(idempotency_key=None)
    again = services.save_roast(
        Roast(
            green_lot=first.green_lot,
            coffee=first.coffee,
            input_g=500,
            output_g=425,
            duration_s=630,
        ),
        idempotency_key=key,
    )
    same = services.save_roast(
        Roast(
            green_lot=first.green_lot,
            coffee=first.coffee,
            input_g=500,
            output_g=425,
            duration_s=630,
        ),
        idempotency_key=key,
    )
    assert again.pk == same.pk
    assert Roast.objects.count() == 2


@pytest.mark.parametrize(
    ("input_g", "output_g", "warn"),
    [(500, 425, False), (500, 480, True), (500, 340, True), (500, 475, False), (500, 350, False)],
)
def test_loss_rate_warning(input_g, output_g, warn):
    assert (services.loss_rate_warning(input_g, output_g) is not None) is warn


# --- 生豆ロット -----------------------------------------------------------------


def test_lot_weight_cannot_go_below_used(lot, make_roast):
    make_roast()  # 520g 使った
    lot.weight_g = 519
    with pytest.raises(StockError):
        services.save_green_lot(lot)
    lot.weight_g = 520
    services.save_green_lot(lot)
    assert lot.remaining() == 0


def test_used_lot_cannot_be_deleted(lot, make_roast):
    make_roast()
    with pytest.raises(ProtectedError):
        lot.delete()


# --- 販売と引当 -----------------------------------------------------------------


def test_sale_allocates_oldest_roast_first(make_roast, product, channel):
    newer = make_roast(roasted_at=datetime(2026, 9, 12, tzinfo=JST), output_g=425)
    older = make_roast(roasted_at=datetime(2026, 9, 10, tzinfo=JST), output_g=300)
    sale = sell(channel, (product, 2))  # 400g

    allocations = {a.roast_id: a.weight_g for a in Allocation.objects.all()}
    assert allocations == {older.pk: 300, newer.pk: 100}
    assert older.remaining() == 0
    assert newer.remaining() == 325

    item = sale.items.get()
    expected = (
        300 * Roast.objects.get(pk=older.pk).cost_per_g
        + 100 * Roast.objects.get(pk=newer.pk).cost_per_g
        + 50 * 2
    )
    assert item.cost_yen == expected


def test_sale_rejects_when_stock_is_short(make_roast, product, channel):
    make_roast()  # 425g
    with pytest.raises(StockError, match="75g 足りません"):
        sell(channel, (product, 1), (product, 1), (product, 1))
    assert not Sale.objects.exists()


def test_sale_keeps_price_at_time_of_sale(make_roast, product, channel):
    make_roast()
    sale = sell(channel, (product, 1))
    product.price_yen = 2000
    product.packaging_cost_yen = 80
    product.save()
    item = sale.items.get()
    assert item.unit_price_yen == 1700
    assert item.packaging_cost_yen == 50


def test_sale_custom_unit_price(make_roast, product, channel):
    make_roast()
    sale = services.save_sale(
        Sale(sold_on=date(2026, 9, 20), channel=channel), [SaleLine(product, 2, 1500)]
    )
    assert sale.amount_yen == 3000


def test_sale_edit_reallocates_only_itself(make_roast, product, channel):
    older = make_roast(roasted_at=datetime(2026, 9, 10, tzinfo=JST), output_g=300)
    newer = make_roast(roasted_at=datetime(2026, 9, 12, tzinfo=JST), output_g=425)
    first = sell(channel, (product, 1))  # older から 200g
    second = sell(channel, (product, 1))  # older 100g + newer 100g

    # 1つ目を 0 個にはできないので、別の商品に替えて作り直す
    small = Product.objects.create(coffee=product.coffee, weight_g=100, price_yen=900)
    services.save_sale(first, [SaleLine(small, 1)])

    second_allocs = {
        a.roast_id: a.weight_g for a in Allocation.objects.filter(sale_item__sale=second)
    }
    assert second_allocs == {older.pk: 100, newer.pk: 100}  # 変わらない
    first_allocs = {
        a.roast_id: a.weight_g for a in Allocation.objects.filter(sale_item__sale=first)
    }
    assert first_allocs == {older.pk: 100}
    assert older.remaining() == 100


def test_sale_edit_can_use_its_own_freed_stock(make_roast, product, channel):
    make_roast()  # 425g
    sale = sell(channel, (product, 2))  # 400g。残り 25g
    services.save_sale(sale, [SaleLine(product, 2, 1600)])  # 同じ量で単価だけ変える
    assert sale.items.get().unit_price_yen == 1600


def test_delete_sale_returns_stock(make_roast, product, channel):
    roast = make_roast()
    sale = sell(channel, (product, 1))
    services.delete_sale(sale)
    assert roast.remaining() == 425
    assert not Allocation.objects.exists()


def test_sale_idempotency(make_roast, product, channel):
    make_roast()
    key = uuid4()
    a = sell(channel, (product, 1), key=key)
    b = sell(channel, (product, 1), key=key)
    assert a.pk == b.pk
    assert Sale.objects.count() == 1


def test_sale_needs_lines(channel):
    with pytest.raises(ValidationError):
        services.save_sale(Sale(channel=channel), [])


def test_plan_allocations_preview_excludes_own_sale(make_roast, product, channel):
    make_roast()  # 425g
    sale = sell(channel, (product, 2))  # 残り 25g
    lines = [SaleLine(product, 2)]
    with pytest.raises(StockError):
        services.plan_allocations(lines)
    plan = services.plan_allocations(lines, exclude_sale=sale)
    assert sum(a.weight_g for a in plan[0]) == 400


# --- 在庫調整 -------------------------------------------------------------------


def test_adjustment_on_roast(make_roast, tasting_reason):
    roast = make_roast()
    services.save_adjustment(
        Adjustment(roast=roast, delta_g=-25, reason=tasting_reason, adjusted_on=date(2026, 9, 11))
    )
    assert roast.remaining() == 400


def test_adjustment_cannot_make_stock_negative(lot, tasting_reason):
    adj = Adjustment(green_lot=lot, delta_g=-5001, reason=tasting_reason)
    with pytest.raises(StockError):
        services.save_adjustment(adj)
    assert adj.pk is None
    assert not Adjustment.objects.exists()


def test_deleting_positive_adjustment_is_checked(lot, make_roast, stocktake_reason):
    plus = services.save_adjustment(Adjustment(green_lot=lot, delta_g=100, reason=stocktake_reason))
    make_roast(input_g=5000, handpick_g=100, output_g=4250)  # 5,100g をすべて使う
    with pytest.raises(StockError):
        services.delete_adjustment(plus)
    assert Adjustment.objects.filter(pk=plus.pk).exists()


def test_adjustment_needs_exactly_one_target(lot, make_roast, tasting_reason):
    roast = make_roast()
    with pytest.raises(ValidationError):
        services.save_adjustment(
            Adjustment(green_lot=lot, roast=roast, delta_g=-1, reason=tasting_reason)
        )
    with pytest.raises(ValidationError):
        services.save_adjustment(Adjustment(delta_g=-1, reason=tasting_reason))


def test_stocktake_records_difference(lot, make_roast, stocktake_reason):
    make_roast()  # 残り 4,480g
    adj = services.record_stocktake(target=lot, actual_g=4450, reason=stocktake_reason)
    assert adj.delta_g == -30
    assert lot.remaining() == 4450
    assert services.record_stocktake(target=lot, actual_g=4450, reason=stocktake_reason) is None


def test_stocktake_on_roast(make_roast, stocktake_reason):
    roast = make_roast()
    adj = services.record_stocktake(target=roast, actual_g=430, reason=stocktake_reason)
    assert adj.delta_g == 5
    assert roast.remaining() == 430


# --- DB の制約（入力チェックをすり抜けても DB が止める） ---------------------------


def test_db_check_constraints(lot, coffee, tasting_reason):
    with pytest.raises(IntegrityError), transaction.atomic():
        Roast.objects.create(
            green_lot=lot, coffee=coffee, input_g=500, output_g=600, duration_s=600
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Adjustment.objects.create(delta_g=-1, reason=tasting_reason)
    with pytest.raises(IntegrityError), transaction.atomic():
        Adjustment.objects.create(green_lot=lot, delta_g=0, reason=tasting_reason)


def test_stock_annotations_do_not_multiply(lot, make_roast, product, channel, tasting_reason):
    """引当と在庫調整が複数あっても、JOIN で合計が膨らまない。"""
    roast = make_roast()
    sell(channel, (product, 1))
    sell(channel, (product, 1))
    for _ in range(3):
        services.save_adjustment(Adjustment(roast=roast, delta_g=-5, reason=tasting_reason))
    row = Roast.objects.with_stock().get(pk=roast.pk)
    assert (row.allocated_g, row.adjusted_g, row.remaining_g) == (400, -15, 10)
    assert Coffee.objects.with_stock().get(pk=roast.coffee_id).remaining_g == 10
