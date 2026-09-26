from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from inventory import services
from inventory.models import ChoiceOption, Coffee, GreenLot, Product, Roast, Supplier

JST = ZoneInfo("Asia/Tokyo")


def choice(category: str, label: str) -> ChoiceOption:
    # transaction=True のテストでは DB が空にされ、マイグレーションの選択肢も消えるので作り直す
    return ChoiceOption.objects.get_or_create(category=category, label=label)[0]


@pytest.fixture
def supplier(db):
    return Supplier.objects.create(name="SPECIALTY COFFEE WATARU")


@pytest.fixture
def make_lot(supplier):
    def make(**kwargs):
        values = {
            "name": "コロンビア ラ・エスペランサ 2026-09",
            "purchased_on": date(2026, 9, 1),
            "supplier": supplier,
            "country": "コロンビア",
            "weight_g": 5000,
            "price_yen": 9000,
            "extra_cost_yen": 1000,
        }
        values.update(kwargs)
        return services.save_green_lot(GreenLot(**values))

    return make


@pytest.fixture
def lot(make_lot):
    """仕様書 5 の計算例：5kg を 9,000円、送料 1,000円で仕入れた。"""
    return make_lot()


@pytest.fixture
def coffee(db):
    return Coffee.objects.create(name="コロンビア ラ・エスペランサ 中煎り")


@pytest.fixture
def product(coffee):
    return Product.objects.create(
        coffee=coffee, weight_g=200, price_yen=1700, packaging_cost_yen=50
    )


@pytest.fixture
def make_roast(lot, coffee):
    def make(**kwargs):
        values = {
            "roasted_at": datetime(2026, 9, 10, 10, 0, tzinfo=JST),
            "green_lot": lot,
            "coffee": coffee,
            "input_g": 500,
            "handpick_g": 20,
            "output_g": 425,
            "duration_s": 630,
            "first_crack_s": 510,
        }
        values.update(kwargs)
        return services.save_roast(Roast(**values))

    return make


@pytest.fixture
def channel(db):
    return choice("sales_channel", "店頭")


@pytest.fixture
def tasting_reason(db):
    return choice("adjustment_reason", "試飲・自家用")


@pytest.fixture
def stocktake_reason(db):
    return choice("adjustment_reason", "棚卸しの差")
