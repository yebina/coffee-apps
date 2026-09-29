"""焙煎記録（仕様書 4.4、画面 #6〜#8）。"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import calc, services
from ..forms import NEW, RoastForm, _parse_min_sec, normalize_number
from ..models import Allocation, Coffee, GreenLot, Roast
from .common import add_service_error, new_key, posted_key
from .lots import lot_previous_roast


def roast_list(request):
    lot_id = request.GET.get("lot", "")
    coffee_id = request.GET.get("coffee", "")
    roasts = Roast.objects.select_related("coffee", "green_lot")
    if lot_id.isdigit():
        roasts = roasts.filter(green_lot_id=lot_id)
    if coffee_id.isdigit():
        roasts = roasts.filter(coffee_id=coffee_id)
    return render(
        request,
        "inventory/roast_list.html",
        {
            "roasts": roasts.order_by("-roasted_at", "-id"),
            "lots": GreenLot.objects.order_by("-purchased_on", "-id"),
            "coffees": Coffee.objects.all(),
            "lot_id": lot_id,
            "coffee_id": coffee_id,
        },
    )


def roast_detail(request, pk):
    roast = get_object_or_404(
        Roast.objects.with_stock().select_related("coffee", "green_lot"), pk=pk
    )
    uses = (
        Allocation.objects.filter(roast=roast)
        .select_related("sale_item__sale__channel", "sale_item__product__coffee")
        .order_by("-sale_item__sale__sold_on", "-id")
    )
    adjustments = roast.adjustments.select_related("reason").order_by("-adjusted_on", "-id")
    return render(
        request,
        "inventory/roast_detail.html",
        {
            "roast": roast,
            "uses": uses,
            "adjustments": adjustments,
            "can_delete": not uses.exists() and not adjustments.exists(),
            "timeline": _timeline(roast.duration_s, roast.first_crack_s, roast.second_crack_s),
        },
    )


def _timeline(total, first, second):
    """焙煎の時間の帯（投入〜1ハゼ、1ハゼ後、2ハゼ）の位置を % で出す。"""
    if not total:
        return None

    def pos(s):
        return None if s is None else f"{s / total * 100:.2f}"

    return {"first": pos(first), "second": pos(second)}


def roast_new(request):
    return _roast_form(request, Roast())


def roast_edit(request, pk):
    roast = get_object_or_404(Roast.objects.select_related("green_lot", "coffee"), pk=pk)
    return _roast_form(request, roast)


def _roast_form(request, roast: Roast):
    editing = roast.pk is not None
    original = Roast.objects.with_stock().get(pk=roast.pk) if editing else None
    loss_warning = None
    if request.method == "POST":
        form = RoastForm(request.POST, instance=roast)
        if form.is_valid():
            data = form.cleaned_data
            loss_warning = services.loss_rate_warning(data["input_g"], data["output_g"])
            if loss_warning and not request.POST.get("confirm_loss"):
                pass  # 確認を出して、もう一度送ってもらう（仕様書 6）
            else:
                loss_warning = None
                try:
                    with transaction.atomic():
                        roast = form.build()
                        if data["coffee_choice"] == NEW:
                            roast.coffee = Coffee.objects.create(name=data["new_coffee"].strip())
                        roast = services.save_roast(roast, idempotency_key=posted_key(request))
                except ValidationError as e:
                    if not editing:
                        roast.pk = None
                    add_service_error(form, e)
                else:
                    if editing:
                        messages.success(request, "焙煎記録を保存しました")
                    else:
                        messages.success(
                            request,
                            f"焙煎を記録しました。{roast.coffee.name} の在庫が "
                            f"{roast.output_g:,} g 増えました",
                        )
                    return redirect("inventory:roast_detail", pk=roast.pk)
        key = request.POST.get("idempotency_key") or new_key()
    else:
        form = RoastForm(instance=roast)
        key = new_key()

    context = {
        "form": form,
        "roast": original,
        "key": key,
        "loss_warning": loss_warning,
        "levels": Roast.RoastLevel.choices,
        "time_fields": [
            ("duration", "焙煎時間", True, "投入から排出まで"),
            ("first", "1ハゼ開始", False, "投入からの時間"),
            ("second", "2ハゼ開始", False, "投入からの時間"),
        ],
        "forms_with_errors": [form] if form.errors else [],
        "coffee_locked": bool(original and original.allocated_g),
    }
    context.update(_preview_context(form.data if form.is_bound else None, form, original))
    return render(request, "inventory/roast_form.html", context)


def _int(value):
    try:
        return int(normalize_number(value))
    except (TypeError, ValueError):
        return None


def _seconds(data, prefix):
    try:
        return _parse_min_sec(data.get(f"{prefix}_m"), data.get(f"{prefix}_sec"), "")
    except ValidationError:
        return None


def _preview_context(data, form, original: Roast | None):
    """入力中の計算（ロス率、原価、1ハゼ後の割合）と、同じロットの前回の記録。"""
    if data is None:
        lot_id = form.initial.get("green_lot") or (original.green_lot_id if original else None)
        input_g = original.input_g if original else None
        handpick_g = original.handpick_g if original else 0
        output_g = original.output_g if original else None
        total = original.duration_s if original else None
        first = original.first_crack_s if original else None
    else:
        lot_id = _int(data.get("green_lot"))
        input_g = _int(data.get("input_g"))
        handpick_g = _int(data.get("handpick_g")) or 0
        output_g = _int(data.get("output_g"))
        total = _seconds(data, "duration")
        first = _seconds(data, "first")

    lot = GreenLot.objects.with_stock().filter(pk=lot_id).first() if lot_id else None
    available = None
    if lot:
        give_back = original.green_used_g if original and original.green_lot_id == lot.pk else 0
        available = lot.remaining_g + give_back

    ctx = {"lot": lot, "available": available}
    if input_g and input_g > 0:
        used = input_g + handpick_g
        ctx["used_g"] = used
        if output_g is not None and 0 <= output_g:
            ctx["loss_rate"] = calc.loss_rate(input_g, output_g)
            ctx["loss_out"] = services.loss_rate_warning(input_g, output_g) is not None
        if lot:
            cost = calc.roast_cost(used, lot.price_per_g)
            ctx["cost"] = cost
            if output_g:
                ctx["cost_per_g"] = calc.roast_cost_per_g(cost, output_g)
    if total and first is not None and first < total:
        ctx["dev_s"] = calc.development_time_s(total, first)
        ctx["dtr"] = calc.development_ratio(total, first)
    ctx["prev"] = lot_previous_roast(lot.pk, before=original) if lot else None
    return ctx


@require_POST
def roast_preview(request):
    """入力中の計算と前回の記録を返す（htmx の out-of-band swap）。"""
    original = None
    pk = request.POST.get("roast_id")
    if pk and pk.isdigit():
        original = Roast.objects.with_stock().filter(pk=pk).first()
    form = RoastForm(instance=original or Roast())
    context = _preview_context(request.POST, form, original)
    context["oob"] = True

    # 新しく記録するときに生豆ロットを選んだら、そのロットの前回の銘柄と焙煎度を入れる
    if request.POST.get("lot_changed") and original is None:
        prev = context["prev"]
        if prev:
            initial = request.POST.dict()
            initial["coffee_choice"] = str(prev.coffee_id)
            initial["roast_level"] = prev.roast_level
            context["preset_form"] = RoastForm(instance=Roast(), initial=initial)
            context["levels"] = Roast.RoastLevel.choices
    return render(request, "inventory/roast_preview.html", context)


@require_POST
def roast_delete(request, pk):
    roast = get_object_or_404(Roast, pk=pk)
    try:
        services.delete_roast(roast)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("inventory:roast_detail", pk=pk)
    messages.success(request, "焙煎記録を削除しました。生豆ロットの残量を戻しました")
    return redirect("inventory:roast_list")
