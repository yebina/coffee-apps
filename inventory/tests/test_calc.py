"""仕様書「5. 計算ルール」の計算例を、そのままテストにする。"""

from decimal import Decimal

import pytest

from inventory import calc


def test_spec_example():
    # 1. 生豆 5kg を 9,000円、送料 1,000円で仕入れた → kg 単価 2,000円（g 単価 2円）
    assert calc.green_price_per_kg(9000, 1000, 5000) == 2000
    per_g = calc.green_price_per_g(9000, 1000, 5000)
    assert per_g == 2

    # 2. 投入量 500g、ハンドピックで 20g、焙煎後重量 425g
    used = calc.green_used_g(500, 20)
    assert used == 520
    assert calc.display_percent(calc.loss_rate(500, 425)) == Decimal("15.0")
    cost = calc.roast_cost(used, per_g)
    assert cost == 1040
    per_g_roasted = calc.roast_cost_per_g(cost, 425)
    assert calc.display_per_g(per_g_roasted) == Decimal("2.45")

    # 3. 焙煎時間 10:30、1ハゼ開始 8:30 → 1ハゼ後の時間 2:00、割合 19.0%
    assert calc.format_mmss(calc.development_time_s(630, 510)) == "2:00"
    assert calc.display_percent(calc.development_ratio(630, 510)) == Decimal("19.0")

    # 4. 200g・1,700円（包材費 50円）を1個販売 → 原価 539円、粗利 1,161円、粗利率 68.3%
    item_cost = calc.sale_item_cost([(200, per_g_roasted)], 50, 1)
    amount = calc.line_amount(1700, 1)
    assert calc.display_yen(item_cost) == 539
    assert calc.display_yen(calc.gross_profit(amount, item_cost)) == 1161
    assert calc.display_percent(calc.gross_margin(amount, item_cost)) == Decimal("68.3")

    # 5. 残量：生豆ロット 5,000 − 520 ＝ 4,480g、焙煎記録 425 − 200 ＝ 225g
    assert calc.green_remaining_g(5000, 520, 0) == 4480
    assert calc.roast_remaining_g(425, 200, 0) == 225


def test_no_rounding_in_the_middle():
    """途中で丸めると、粗利は 1,700 − (200 × 2.45 + 50) = 1,160 になってしまう。"""
    per_g = calc.roast_cost_per_g(Decimal(1040), 425)
    cost = calc.sale_item_cost([(200, per_g)], 50, 1)
    assert calc.display_yen(calc.gross_profit(1700, cost)) == 1161


@pytest.mark.parametrize(
    ("value", "expected"),
    [(Decimal("0.5"), 1), (Decimal("1.5"), 2), (Decimal("2.5"), 3), (Decimal("-0.5"), -1)],
)
def test_display_yen_rounds_half_up(value, expected):
    # Python の round() なら 2.5 → 2 になる
    assert calc.display_yen(value) == expected


def test_display_percent_rounds_half_up():
    assert calc.display_percent(Decimal("0.12345")) == Decimal("12.3")
    assert calc.display_percent(Decimal("0.12350")) == Decimal("12.4")
    assert calc.display_percent(None) is None


def test_gross_margin_zero_amount():
    assert calc.gross_margin(0, 100) is None


def test_development_without_first_crack():
    assert calc.development_time_s(630, None) is None
    assert calc.development_ratio(630, None) is None


@pytest.mark.parametrize(("text", "seconds"), [("10:30", 630), ("0:05", 5), ("90", 90)])
def test_parse_mmss(text, seconds):
    assert calc.parse_mmss(text) == seconds
    assert calc.parse_mmss(calc.format_mmss(seconds)) == seconds


@pytest.mark.parametrize("text", ["10:60", "-1", "a:b", "1:-1"])
def test_parse_mmss_rejects_bad_input(text):
    with pytest.raises(ValueError):
        calc.parse_mmss(text)
