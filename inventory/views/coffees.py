"""銘柄・商品（仕様書 4.3、画面 #9・#10）。"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import CoffeeForm, ProductForm
from ..models import Coffee, Product, Roast


def coffee_cards(coffees):
    """銘柄ごとの残量、商品と何個分あるか、焙煎記録ごとの残量。"""
    today = timezone.localdate()
    cards = []
    for coffee in coffees:
        roasts = list(
            Roast.objects.with_stock()
            .filter(coffee=coffee)
            .select_related("green_lot")
            .order_by("roasted_at", "id")
        )
        in_stock = [r for r in roasts if r.remaining_g > 0]
        remaining = coffee.remaining_g
        products = [
            {"product": p, "packs": max(0, remaining) // p.weight_g}
            for p in coffee.products.order_by("weight_g")
        ]
        oldest = in_stock[0] if in_stock else None
        cards.append(
            {
                "coffee": coffee,
                "remaining_g": remaining,
                "products": products,
                "stock_roasts": in_stock,
                "latest": roasts[-1] if roasts else None,
                "oldest_days": (
                    (today - timezone.localtime(oldest.roasted_at).date()).days if oldest else None
                ),
                "packs_text": "・".join(
                    f"{row['product'].weight_g}g×{row['packs']}"
                    for row in sorted(products, key=lambda r: -r["product"].weight_g)
                    if row["product"].is_active
                ),
            }
        )
    return cards


def coffee_list(request):
    show_all = request.GET.get("show") == "all"
    coffees = Coffee.objects.with_stock()
    if not show_all:
        coffees = coffees.filter(is_active=True)
    return render(
        request,
        "inventory/coffee_list.html",
        {
            "cards": coffee_cards(coffees),
            "show_all": show_all,
            "coffee_form": CoffeeForm(),
            "product_form": ProductForm(),
        },
    )


@require_POST
def coffee_create(request):
    form = CoffeeForm(request.POST)
    if form.is_valid():
        coffee = form.save()
        messages.success(
            request, f"銘柄「{coffee.name}」を追加しました。商品（内容量と価格）も追加してください"
        )
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("inventory:coffee_list")


@require_POST
def coffee_toggle(request, pk):
    coffee = get_object_or_404(Coffee, pk=pk)
    coffee.is_active = not coffee.is_active
    coffee.save(update_fields=["is_active", "updated_at"])
    messages.success(
        request, f"{coffee.name} の販売を{'再開しました' if coffee.is_active else 'やめました'}"
    )
    return redirect(request.POST.get("next") or "inventory:coffee_list")


@require_POST
def product_create(request, pk):
    coffee = get_object_or_404(Coffee, pk=pk)
    form = ProductForm(request.POST, instance=Product(coffee=coffee))
    if form.is_valid():
        product = form.save()
        messages.success(request, f"{coffee.name} に {product.weight_g}g の商品を追加しました")
    else:
        errors = [e for errs in form.errors.values() for e in errs]
        messages.error(request, "商品を追加できません：" + " ".join(errors))
    return redirect("inventory:coffee_list")


@require_POST
def product_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active", "updated_at"])
    return redirect("inventory:coffee_list")
