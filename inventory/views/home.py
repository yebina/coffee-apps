"""ホーム（仕様書 4.7、画面 #2）と、スマホ用の「その他」。"""

from django.shortcuts import render
from django.utils import timezone

from .. import calc
from ..models import Coffee, GreenLot, Sale
from .coffees import coffee_cards
from .sales import sales_with_totals


def month_summary(sales) -> dict:
    amount = sum(s.amount_yen for s in sales)
    cost = sum((s.cost_yen for s in sales), calc.ZERO)
    grams = sum(item.weight_g for s in sales for item in s.items.all())
    return {
        "count": len(sales),
        "amount": amount,
        "cost": cost,
        "profit": calc.gross_profit(amount, cost),
        "margin": calc.gross_margin(amount, cost),
        "grams": grams,
    }


def home(request):
    today = timezone.localdate()
    sales = list(
        sales_with_totals(Sale.objects.filter(sold_on__year=today.year, sold_on__month=today.month))
    )
    coffees = [c for c in Coffee.objects.with_stock() if c.is_active or c.remaining_g > 0]
    lots = GreenLot.objects.in_stock().select_related("supplier").order_by("purchased_on", "id")
    return render(
        request,
        "inventory/home.html",
        {
            "today": today,
            "month": month_summary(sales),
            "cards": coffee_cards(coffees),
            "lots": lots,
        },
    )


def menu(request):
    return render(request, "inventory/menu.html")
