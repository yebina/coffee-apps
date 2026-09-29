"""販売（仕様書 4.5、画面 #11〜#13）。"""

from collections import OrderedDict

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import calc, services
from ..forms import SaleForm, SaleItemFormSet, normalize_number
from ..models import Allocation, Coffee, Product, Sale
from ..services import SaleLine
from .common import add_service_error, new_key, posted_key

ITEM_PREFIX = "items"


def sales_with_totals(queryset):
    """金額・原価の計算に使う行を、まとめて読み込む。"""
    return queryset.select_related("channel").prefetch_related(
        "items__product__coffee",
        Prefetch(
            "items__allocations",
            queryset=Allocation.objects.select_related("roast__green_lot"),
        ),
    )


def sale_list(request):
    today = timezone.localdate()
    months = sorted(
        {(d.year, d.month) for d in Sale.objects.dates("sold_on", "month")}, reverse=True
    )
    month = request.GET.get("month")
    if month is None:
        month = f"{today:%Y-%m}" if (today.year, today.month) in months else "all"
    sales = Sale.objects.order_by("-sold_on", "-id")
    if month != "all":
        try:
            year, mon = (int(x) for x in month.split("-"))
            sales = sales.filter(sold_on__year=year, sold_on__month=mon)
        except ValueError:
            month = "all"
    sales = list(sales_with_totals(sales))
    amount = sum(s.amount_yen for s in sales)
    cost = sum(s.cost_yen for s in sales)
    return render(
        request,
        "inventory/sale_list.html",
        {
            "sales": sales,
            "months": [(f"{y}-{m:02d}", (y, m)) for y, m in months],
            "month": month,
            "amount": amount,
            "profit": calc.gross_profit(amount, cost),
        },
    )


def sale_detail(request, pk):
    sale = get_object_or_404(sales_with_totals(Sale.objects.all()), pk=pk)
    items = list(sale.items.all())
    return render(
        request,
        "inventory/sale_detail.html",
        {
            "sale": sale,
            "items": items,
            "quantity": sum(i.quantity for i in items),
            "margin": calc.gross_margin(sale.amount_yen, sale.cost_yen),
        },
    )


# ---------------------------------------------------------------------------
# 登録・編集
# ---------------------------------------------------------------------------


def _rows_from_post(data) -> list[dict]:
    """送られてきた明細の行（入力途中のものも含む）。"""
    try:
        total = int(data.get(f"{ITEM_PREFIX}-TOTAL_FORMS", 0))
    except ValueError:
        total = 0
    rows = []
    for i in range(min(total, 100)):
        get = lambda name, i=i: data.get(f"{ITEM_PREFIX}-{i}-{name}", "")  # noqa: E731
        rows.append(
            {
                "product": get("product"),
                "quantity": get("quantity"),
                "unit_price_yen": get("unit_price_yen"),
                "prev_product": get("prev_product"),
            }
        )
    return rows


def _blank_row() -> dict:
    return {"product": "", "quantity": 1, "unit_price_yen": "", "prev_product": ""}


def _lines_from_rows(rows) -> list[SaleLine | None]:
    """計算に使える行だけを SaleLine にする（使えない行は None）。"""
    ids = {r["product"] for r in rows if str(r["product"]).isdigit()}
    products = Product.objects.select_related("coffee").in_bulk([int(i) for i in ids])
    lines = []
    for r in rows:
        product = products.get(int(r["product"])) if str(r["product"]).isdigit() else None
        try:
            qty = int(normalize_number(r["quantity"]))
        except ValueError:
            qty = 0
        try:
            price = int(normalize_number(r["unit_price_yen"]))
        except ValueError:
            price = None
        lines.append(SaleLine(product, qty, price) if product and qty >= 1 else None)
    return lines


def _live_context(rows, sale: Sale | None) -> dict:
    """入力中の金額・原価の見込み・在庫のチェック・引当の予定。"""
    lines = [line for line in _lines_from_rows(rows) if line]
    if not lines:
        return {"has_lines": False, "total": 0}
    plan = services.preview_allocations(lines, exclude_sale=sale)
    total = sum(line.price * line.quantity for line in lines)
    cost = sum((plan.item_cost(i) for i in range(len(lines))), calc.ZERO)
    return {
        "has_lines": True,
        "total": total,
        "est_cost": cost,
        "est_profit": calc.gross_profit(total, cost),
        "est_margin": calc.gross_margin(total, cost),
        "stock_rows": plan.stock_rows(),
        "plan_rows": [
            {"line": line, "roast": a.roast, "weight_g": a.weight_g}
            for line, allocations in zip(lines, plan.allocations, strict=True)
            for a in allocations
        ],
    }


def _product_groups(sale: Sale | None):
    """商品の選択肢。販売中の銘柄・商品と、この販売ですでに使っている商品。"""
    used = set(sale.items.values_list("product_id", flat=True)) if sale else set()
    groups = OrderedDict()
    coffees = Coffee.objects.with_stock().order_by("name")
    products = Product.objects.select_related("coffee").order_by("coffee__name", "weight_g")
    remaining = {c.pk: c.remaining_g for c in coffees}
    for p in products:
        if not ((p.is_active and p.coffee.is_active) or p.pk in used):
            continue
        groups.setdefault(p.coffee, {"remaining_g": remaining.get(p.coffee_id, 0), "products": []})
        groups[p.coffee]["products"].append(p)
    return groups


def sale_new(request):
    return _sale_form(request, None)


def sale_edit(request, pk):
    return _sale_form(request, get_object_or_404(Sale, pk=pk))


def _sale_form(request, sale: Sale | None):
    editing = sale is not None
    if request.method == "POST":
        form = SaleForm(request.POST, channel=sale.channel if sale else None)
        formset = SaleItemFormSet(request.POST, prefix=ITEM_PREFIX)
        rows = _rows_from_post(request.POST)
        if form.is_valid() and formset.is_valid():
            filled = [f for f in formset if not f.is_blank()]
            lines = []
            for f in filled:
                if not f.cleaned_data.get("quantity"):
                    f.add_error("quantity", "数量は 1 以上の整数で入力してください。")
                    continue
                lines.append(
                    SaleLine(
                        f.cleaned_data["product"],
                        f.cleaned_data["quantity"],
                        f.cleaned_data.get("unit_price_yen"),
                    )
                )
            if not filled:
                form.add_error(None, "商品を 1 つ以上選んでください。")
            elif len(lines) == len(filled):
                target = sale or Sale()
                for name in ("sold_on", "channel", "customer", "memo"):
                    setattr(target, name, form.cleaned_data[name])
                try:
                    target = services.save_sale(target, lines, idempotency_key=posted_key(request))
                except ValidationError as e:
                    if not editing:
                        target.pk = None
                    add_service_error(form, e)
                else:
                    if editing:
                        messages.success(request, "販売を保存しました。引当をやり直しました")
                    else:
                        amount = sum(line.price * line.quantity for line in lines)
                        messages.success(
                            request,
                            f"販売を記録しました（¥{amount:,}）。在庫から古い順に出しました",
                        )
                    return redirect("inventory:sale_detail", pk=target.pk)
        key = request.POST.get("idempotency_key") or new_key()
        show_errors = True
    else:
        if sale:
            form = SaleForm(
                initial={
                    "sold_on": sale.sold_on,
                    "channel": sale.channel_id,
                    "customer": sale.customer,
                    "memo": sale.memo,
                },
                channel=sale.channel,
            )
            rows = [
                {
                    "product": item.product_id,
                    "quantity": item.quantity,
                    "unit_price_yen": item.unit_price_yen,
                    "prev_product": item.product_id,
                }
                for item in sale.items.all()
            ]
        else:
            form = SaleForm(initial={"sold_on": timezone.localdate()})
            rows = [_blank_row()]
        formset = SaleItemFormSet(initial=rows, prefix=ITEM_PREFIX)
        key = new_key()
        show_errors = False

    context = {
        "form": form,
        "formset": formset,
        "sale": sale,
        "key": key,
        "groups": _product_groups(sale),
        "show_errors": show_errors,
        "forms_with_errors": [f for f in [form, *formset] if f.errors] if show_errors else [],
    }
    context.update(_live_context(rows, sale))
    return render(request, "inventory/sale_form.html", context)


@require_POST
def sale_preview(request):
    """入力中の計算（htmx）。明細の行を足す・消す・商品を選び直すときは、明細も作り直す。"""
    sale = None
    pk = request.POST.get("sale_id", "")
    if pk.isdigit():
        sale = Sale.objects.filter(pk=pk).first()
    rows = _rows_from_post(request.POST)
    action = request.POST.get("action", "")
    refresh_items = bool(action)
    if action == "add":
        rows.append(_blank_row())
    elif action.startswith("remove:"):
        index = action.split(":", 1)[1]
        if index.isdigit() and int(index) < len(rows):
            rows.pop(int(index))
        if not rows:
            rows.append(_blank_row())
    elif action == "product":
        # 商品を選び直した行は、単価を商品の販売価格にする（仕様書 4.5）
        prices = dict(Product.objects.values_list("pk", "price_yen"))
        for r in rows:
            if r["product"] != r["prev_product"]:
                if str(r["product"]).isdigit():
                    r["unit_price_yen"] = prices.get(int(r["product"]), "")
                r["prev_product"] = r["product"]

    context = _live_context(rows, sale)
    context["oob"] = True
    context["row_amounts"] = [
        line.price * line.quantity if line else None for line in _lines_from_rows(rows)
    ]
    if refresh_items:
        context["formset"] = SaleItemFormSet(initial=rows, prefix=ITEM_PREFIX)
        context["groups"] = _product_groups(sale)
    return render(request, "inventory/sale_preview.html", context)


@require_POST
def sale_delete(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    services.delete_sale(sale)
    messages.success(request, "販売を削除して、在庫を戻しました")
    return redirect("inventory:sale_list")
