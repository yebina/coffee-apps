"""集計（仕様書 4.8、画面 #15）。"""

from datetime import date

from django.shortcuts import render
from django.utils import timezone

from .. import calc
from ..models import Sale
from .sales import sales_with_totals

PERIODS = [("this", "今月"), ("last", "先月"), ("3m", "過去3か月"), ("all", "すべて")]


def _add_months(d: date, n: int) -> date:
    index = d.year * 12 + d.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def report(request):
    today = timezone.localdate()
    this_month = today.replace(day=1)
    sales = list(sales_with_totals(Sale.objects.order_by("sold_on")))

    # 月別：売上・原価・粗利・粗利率・販売した重さ
    months: dict[tuple[int, int], dict] = {}
    for s in sales:
        m = months.setdefault(
            (s.sold_on.year, s.sold_on.month),
            {
                "ym": (s.sold_on.year, s.sold_on.month),
                "amount": 0,
                "cost": calc.ZERO,
                "grams": 0,
                "count": 0,
            },
        )
        m["amount"] += s.amount_yen
        m["cost"] += s.cost_yen
        m["grams"] += sum(i.weight_g for i in s.items.all())
        m["count"] += 1
    month_rows = sorted(months.values(), key=lambda m: m["ym"])
    for m in month_rows:
        m["profit"] = calc.gross_profit(m["amount"], m["cost"])
        m["margin"] = calc.gross_margin(m["amount"], m["cost"])
    total = {
        "amount": sum(m["amount"] for m in month_rows),
        "cost": sum((m["cost"] for m in month_rows), calc.ZERO),
        "grams": sum(m["grams"] for m in month_rows),
        "count": sum(m["count"] for m in month_rows),
    }
    total["profit"] = calc.gross_profit(total["amount"], total["cost"])
    total["margin"] = calc.gross_margin(total["amount"], total["cost"])

    # 棒グラフ（直近12か月）
    chart = month_rows[-12:]
    top = max((m["amount"] for m in chart), default=0) or 1
    for m in chart:
        m["bar_px"] = max(2, round(m["amount"] / top * 150))
    compact = len(chart) > 6

    # 銘柄別（期間を指定）：販売した重さ・売上・粗利
    period = request.GET.get("period", "3m")
    if period == "this":
        start, end = this_month, _add_months(this_month, 1)
    elif period == "last":
        start, end = _add_months(this_month, -1), this_month
    elif period == "all":
        start, end = date.min, date.max
    else:
        period = "3m"
        start, end = _add_months(this_month, -2), _add_months(this_month, 1)
    by_coffee: dict[int, dict] = {}
    for s in sales:
        if not start <= s.sold_on < end:
            continue
        for item in s.items.all():
            coffee = item.product.coffee
            row = by_coffee.setdefault(
                coffee.pk, {"coffee": coffee, "grams": 0, "amount": 0, "cost": calc.ZERO}
            )
            row["grams"] += item.weight_g
            row["amount"] += item.amount_yen
            row["cost"] += item.cost_yen
    coffee_rows = sorted(by_coffee.values(), key=lambda r: -r["amount"])
    for r in coffee_rows:
        r["profit"] = calc.gross_profit(r["amount"], r["cost"])
        r["margin"] = calc.gross_margin(r["amount"], r["cost"])
    coffee_total = {
        "grams": sum(r["grams"] for r in coffee_rows),
        "amount": sum(r["amount"] for r in coffee_rows),
        "cost": sum((r["cost"] for r in coffee_rows), calc.ZERO),
    }
    coffee_total["profit"] = calc.gross_profit(coffee_total["amount"], coffee_total["cost"])
    coffee_total["margin"] = calc.gross_margin(coffee_total["amount"], coffee_total["cost"])

    return render(
        request,
        "inventory/report.html",
        {
            "chart": chart,
            "compact": compact,
            "month_rows": list(reversed(month_rows)),
            "total": total,
            "periods": PERIODS,
            "period": period,
            "coffee_rows": coffee_rows,
            "coffee_total": coffee_total,
        },
    )
