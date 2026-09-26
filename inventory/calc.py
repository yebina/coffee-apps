"""計算ルール（仕様書「5. 計算ルール」）。

画面の表示・保存・集計のすべてがこのモジュールを使う。
- 途中の計算は Decimal で行い、端数を丸めない。
- 丸めるのは表示するときだけ（display_* 関数）。Python の round() は偶数丸めなので使わず、
  ROUND_HALF_UP で四捨五入する。
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value)


# --- 生豆 -------------------------------------------------------------------


def green_price_per_kg(price_yen: int, extra_cost_yen: int, weight_g: int) -> Decimal:
    """生豆の kg 単価 ＝（仕入れ値 ＋ 送料などの経費）÷ 仕入れ重量"""
    return _d(price_yen + extra_cost_yen) * 1000 / _d(weight_g)


def green_price_per_g(price_yen: int, extra_cost_yen: int, weight_g: int) -> Decimal:
    return _d(price_yen + extra_cost_yen) / _d(weight_g)


def green_used_g(input_g: int, handpick_g: int) -> int:
    """生豆使用量 ＝ 投入量 ＋ ハンドピックで除いた量"""
    return input_g + handpick_g


def green_remaining_g(weight_g: int, used_total_g: int, adjusted_total_g: int) -> int:
    """生豆ロットの残量 ＝ 仕入れ重量 − 生豆使用量の合計 ＋ 在庫調整の合計"""
    return weight_g - used_total_g + adjusted_total_g


# --- 焙煎 -------------------------------------------------------------------


def loss_rate(input_g: int, output_g: int) -> Decimal:
    """ロス率 ＝（投入量 − 焙煎後重量）÷ 投入量。ハンドピックで除いた量は含めない"""
    return _d(input_g - output_g) / _d(input_g)


def roast_cost(green_used: int, green_price_per_g_yen: Decimal) -> Decimal:
    """焙煎の原価 ＝ 生豆使用量 × 生豆の g 単価"""
    return _d(green_used) * green_price_per_g_yen


def roast_cost_per_g(cost_yen: Decimal, output_g: int) -> Decimal:
    """1g あたり原価 ＝ 焙煎の原価 ÷ 焙煎後重量"""
    return cost_yen / _d(output_g)


def roast_remaining_g(output_g: int, allocated_total_g: int, adjusted_total_g: int) -> int:
    """焙煎記録の残量 ＝ 焙煎後重量 − 引当の合計 ＋ 在庫調整の合計"""
    return output_g - allocated_total_g + adjusted_total_g


def development_time_s(duration_s: int, first_crack_s: int | None) -> int | None:
    """1ハゼ後の時間 ＝ 焙煎時間 − 1ハゼ開始"""
    if first_crack_s is None:
        return None
    return duration_s - first_crack_s


def development_ratio(duration_s: int, first_crack_s: int | None) -> Decimal | None:
    """1ハゼ後の割合（DTR）＝ 1ハゼ後の時間 ÷ 焙煎時間"""
    dev = development_time_s(duration_s, first_crack_s)
    if dev is None:
        return None
    return _d(dev) / _d(duration_s)


# --- 販売 -------------------------------------------------------------------


def line_amount(unit_price_yen: int, quantity: int) -> int:
    """金額 ＝ 単価 × 数量"""
    return unit_price_yen * quantity


def sale_item_cost(
    allocations: Iterable[tuple[int, Decimal]], packaging_cost_yen: int, quantity: int
) -> Decimal:
    """販売明細の原価 ＝ 引当ごとの「重さ × 焙煎記録の 1g あたり原価」の合計 ＋ 包材費 × 数量

    allocations は (重さ g, 1g あたり原価) の組。
    """
    beans = sum((_d(weight) * per_g for weight, per_g in allocations), ZERO)
    return beans + _d(packaging_cost_yen * quantity)


def gross_profit(amount_yen, cost_yen) -> Decimal:
    """粗利 ＝ 金額 − 原価"""
    return _d(amount_yen) - _d(cost_yen)


def gross_margin(amount_yen, cost_yen) -> Decimal | None:
    """粗利率 ＝ 粗利 ÷ 金額。金額が 0 のときは出さない"""
    if _d(amount_yen) == 0:
        return None
    return gross_profit(amount_yen, cost_yen) / _d(amount_yen)


# --- 表示用の丸め（仕様書 5 の注記） -------------------------------------------


def display_yen(value) -> int:
    """金額は円未満を四捨五入する。"""
    return int(_d(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def display_percent(rate) -> Decimal | None:
    """率は % にして小数第1位まで（例：0.15 → 15.0）。"""
    if rate is None:
        return None
    return (_d(rate) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def display_per_g(value) -> Decimal:
    """g 単価は小数第2位まで。"""
    return _d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_mmss(seconds: int | None) -> str:
    """秒を「分:秒」にする（例：630 → 10:30）。"""
    if seconds is None:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_mmss(text: str) -> int:
    """「分:秒」または秒数の文字を秒にする（例：「10:30」→ 630）。"""
    text = text.strip()
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        m, s = int(minutes), int(seconds)
        if m < 0 or not 0 <= s < 60:
            raise ValueError(f"時間の形式が正しくありません: {text}")
        return m * 60 + s
    value = int(text)
    if value < 0:
        raise ValueError(f"時間の形式が正しくありません: {text}")
    return value
