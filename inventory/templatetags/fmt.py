"""表示の書式。丸めは calc.py の表示用関数に任せる（仕様書 5 の注記）。"""

from datetime import date, datetime
from decimal import Decimal

from django import template
from django.utils import timezone
from django.utils.html import format_html

from inventory import calc
from inventory.models import Roast

register = template.Library()

DASH = "—"
WEEK = "月火水木金土日"

# 焙煎度の色（デモと同じ）
LEVEL_COLORS = {
    Roast.RoastLevel.LIGHT: "#D8BE92",
    Roast.RoastLevel.CINNAMON: "#C49A69",
    Roast.RoastLevel.MEDIUM: "#A97A4C",
    Roast.RoastLevel.HIGH: "#8E6039",
    Roast.RoastLevel.CITY: "#734A2B",
    Roast.RoastLevel.FULL_CITY: "#5A361F",
    Roast.RoastLevel.FRENCH: "#402616",
    Roast.RoastLevel.ITALIAN: "#2A1910",
}


def _num(value):
    return value is not None and value != ""


@register.filter
def yen(value):
    """¥1,234（円未満を四捨五入）"""
    if not _num(value):
        return DASH
    return f"¥{calc.display_yen(value):,}"


@register.filter
def grams(value):
    if not _num(value):
        return DASH
    return f"{int(value):,} g"


@register.filter
def kg(value, digits=2):
    """g を kg で表示する（例：4480 → 4.48 kg）。"""
    if not _num(value):
        return DASH
    q = Decimal(1).scaleb(-int(digits))
    return f"{(Decimal(value) / 1000).quantize(q):,} kg"


@register.filter
def pct(rate):
    if not _num(rate):
        return DASH
    value = calc.display_percent(rate)
    return DASH if value is None else f"{value}%"


@register.filter
def per_g(value):
    if not _num(value):
        return DASH
    return f"{calc.display_per_g(value)} 円/g"


@register.filter
def mmss(seconds):
    if not _num(seconds):
        return DASH
    return calc.format_mmss(int(seconds))


@register.filter
def signed_g(value):
    value = int(value) if _num(value) else 0
    sign = "＋" if value > 0 else "−" if value < 0 else "±"
    return f"{sign}{abs(value):,} g"


@register.filter
def ymd(value):
    if not value:
        return DASH
    if isinstance(value, datetime):
        value = timezone.localtime(value).date()
    return f"{value:%Y/%m/%d}"


@register.filter
def ymd_hm(value):
    if not value:
        return DASH
    return f"{timezone.localtime(value):%Y/%m/%d %H:%M}"


@register.filter
def long_date(value: date):
    return f"{value.year}年{value.month}月{value.day}日（{WEEK[value.weekday()]}）"


@register.filter
def month_label(value):
    """(年, 月) または date を「2026年9月」にする。"""
    if isinstance(value, tuple):
        return f"{value[0]}年{value[1]}月"
    return f"{value.year}年{value.month}月"


@register.filter
def level_color(level):
    return LEVEL_COLORS.get(level, "transparent")


@register.simple_tag
def level_chip(roast_or_level):
    level = getattr(roast_or_level, "roast_level", roast_or_level)
    if not level:
        return ""
    return format_html(
        '<span class="chip"><span class="swatch" style="background:{}"></span>{}</span>',
        LEVEL_COLORS.get(level, "transparent"),
        Roast.RoastLevel(level).label,
    )


@register.simple_tag
def rating_stars(value):
    if not value:
        return format_html('<span class="muted">未評価</span>')
    return format_html(
        '<span class="rating" aria-label="評価 {} / 5">{}<span class="off">{}</span></span>',
        value,
        "★" * value,
        "★" * (5 - value),
    )


@register.simple_tag
def meter(value, maximum):
    ratio = 0 if not maximum else max(0, min(1, (value or 0) / maximum))
    return format_html(
        '<div class="meter" aria-hidden="true"><span style="width:{}%"></span></div>',
        f"{ratio * 100:.1f}",
    )


@register.filter
def dash(value):
    return DASH if value in (None, "") else value


@register.filter
def per_kg_to_g(value):
    return None if value is None else value / 1000


@register.filter
def num(value):
    """桁区切りの整数（例：1,500）。"""
    return DASH if not _num(value) else f"{int(value):,}"


@register.filter
def times(value, other):
    """入力中の「数量 × 単価」。数字でなければ None。"""
    from inventory.forms import normalize_number

    try:
        return int(normalize_number(value)) * int(normalize_number(other))
    except (TypeError, ValueError):
        return None


@register.filter
def ratio(value, total):
    """value ÷ total（率の表示用）。"""
    if not _num(value) or not total:
        return None
    return Decimal(value) / Decimal(total)


@register.filter
def times_dec(value, other):
    return None if value is None or other is None else Decimal(value) * Decimal(other)


@register.filter
def yen_man(value):
    """グラフの短い表示（例：¥1.2万）。"""
    if not _num(value):
        return DASH
    if value >= 10000:
        return f"¥{Decimal(value) / 10000:.1f}万"
    return yen(value)
