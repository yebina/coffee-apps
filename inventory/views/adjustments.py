"""在庫調整（仕様書 4.6、画面 #14）。"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import services
from ..forms import AdjustmentForm, normalize_number
from ..models import Adjustment, GreenLot, Roast
from .common import add_service_error, new_key, posted_key


def _target_choices(selected: str = ""):
    """対象の選択肢。焙煎豆は銘柄ごとに、残量のある焙煎記録を古い順に並べる（仕様書 4.6）。"""
    groups: dict[str, list] = {}
    roasts = (
        Roast.objects.with_stock()
        .select_related("coffee")
        .order_by("coffee__name", "roasted_at", "id")
    )
    for r in roasts:
        value = f"roast:{r.pk}"
        if r.remaining_g <= 0 and value != selected:
            continue
        label = f"{timezone.localtime(r.roasted_at):%Y/%m/%d} 焙煎（残り {r.remaining_g:,} g）"
        groups.setdefault(f"焙煎豆：{r.coffee.name}", []).append((value, label))
    lots = GreenLot.objects.with_stock().order_by("-purchased_on", "-id")
    lot_choices = [
        (f"lot:{lot.pk}", f"{lot.name}（残り {lot.remaining_g:,} g）")
        for lot in lots
        if lot.remaining_g > 0 or f"lot:{lot.pk}" == selected
    ]
    choices = list(groups.items())
    if lot_choices:
        choices.append(("生豆", lot_choices))
    return choices


def _current_remaining(target: str):
    kind, _, pk = (target or "").partition(":")
    if not pk.isdigit():
        return None
    if kind == "lot":
        row = GreenLot.objects.with_stock().filter(pk=pk).first()
    elif kind == "roast":
        row = Roast.objects.with_stock().filter(pk=pk).first()
    else:
        return None
    return row.remaining_g if row else None


def _calc_context(data) -> dict:
    current = _current_remaining(data.get("target"))
    delta = None
    try:
        if data.get("mode") == AdjustmentForm.MODE_COUNT:
            actual = int(normalize_number(data.get("actual_g")))
            delta = actual - current if current is not None else None
        else:
            delta = int(normalize_number(data.get("delta_g")))
    except (TypeError, ValueError):
        delta = None
    after = current + delta if current is not None and delta is not None else None
    return {"current": current, "delta": delta, "after": after}


def adjust(request):
    if request.method == "POST":
        selected = request.POST.get("target", "")
        form = AdjustmentForm(request.POST, target_choices=_target_choices(selected))
        if form.is_valid():
            target = form.target_object()
            data = form.cleaned_data
            try:
                if data["mode"] == AdjustmentForm.MODE_COUNT:
                    adjustment = services.record_stocktake(
                        target=target,
                        actual_g=data["actual_g"],
                        reason=data["reason"],
                        adjusted_on=data["adjusted_on"],
                        memo=data["memo"],
                        idempotency_key=posted_key(request),
                    )
                    if adjustment is None:
                        raise ValidationError(
                            "実際の残量が今の残量と同じなので、調整はいりません。"
                        )
                else:
                    adjustment = services.save_adjustment(
                        Adjustment(
                            green_lot=target if isinstance(target, GreenLot) else None,
                            roast=target if isinstance(target, Roast) else None,
                            delta_g=data["delta_g"],
                            reason=data["reason"],
                            adjusted_on=data["adjusted_on"],
                            memo=data["memo"],
                        ),
                        idempotency_key=posted_key(request),
                    )
            except ValidationError as e:
                add_service_error(form, e)
            else:
                sign = "＋" if adjustment.delta_g > 0 else "−"
                messages.success(
                    request, f"在庫を調整しました（{sign}{abs(adjustment.delta_g):,} g）"
                )
                if adjustment.green_lot_id:
                    return redirect("inventory:lot_detail", pk=adjustment.green_lot_id)
                return redirect("inventory:roast_detail", pk=adjustment.roast_id)
        key = request.POST.get("idempotency_key") or new_key()
        calc_data = request.POST
    else:
        selected = request.GET.get("target", "")
        form = AdjustmentForm(
            initial={"target": selected, "mode": AdjustmentForm.MODE_DELTA},
            target_choices=_target_choices(selected),
        )
        key = new_key()
        calc_data = {"target": selected}

    recent = Adjustment.objects.select_related("green_lot", "roast__coffee", "reason").order_by(
        "-adjusted_on", "-id"
    )[:50]
    context = {
        "form": form,
        "key": key,
        "recent": recent,
        "forms_with_errors": [form] if form.errors else [],
    }
    context.update(_calc_context(calc_data))
    return render(request, "inventory/adjust.html", context)


@require_POST
def adjust_preview(request):
    context = _calc_context(request.POST)
    context["oob"] = True
    return render(request, "inventory/partials/adjust_calc.html", context)


@require_POST
def adjust_delete(request, pk):
    adjustment = get_object_or_404(Adjustment, pk=pk)
    try:
        services.delete_adjustment(adjustment)
    except ValidationError:
        messages.error(request, "この調整を消すと残量がマイナスになるため、削除できません")
    else:
        messages.success(request, "在庫調整を削除しました")
    return redirect("inventory:adjust")
