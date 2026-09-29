"""生豆ロット（仕様書 4.2、画面 #3〜#5）。"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import services
from ..forms import LOT_SUGGEST_FIELDS, NEW, GreenLotForm, lot_copy_initial, lot_kg_price
from ..models import GreenLot, Roast, Supplier
from .common import add_service_error

FILTERS = [("stock", "在庫あり"), ("empty", "使い切り"), ("all", "すべて")]


def lot_list(request):
    current = request.GET.get("f", "stock")
    q = request.GET.get("q", "").strip()
    lots = GreenLot.objects.with_stock().select_related("supplier", "process", "rank")
    if current == "stock":
        lots = lots.filter(remaining_g__gt=0, is_active=True)
    elif current == "empty":
        lots = lots.filter(remaining_g__lte=0)
    if q:
        lots = lots.filter(
            Q(name__icontains=q)
            | Q(product_name__icontains=q)
            | Q(country__icontains=q)
            | Q(area__icontains=q)
            | Q(farm__icontains=q)
            | Q(variety__icontains=q)
        )
    return render(
        request,
        "inventory/lot_list.html",
        {"lots": lots, "filters": FILTERS, "current": current, "q": q},
    )


def lot_detail(request, pk):
    lot = get_object_or_404(
        GreenLot.objects.with_stock().select_related("supplier", "process", "rank"), pk=pk
    )
    roasts = lot.roasts.select_related("coffee").order_by("-roasted_at", "-id")
    adjustments = lot.adjustments.select_related("reason").order_by("-adjusted_on", "-id")
    return render(
        request,
        "inventory/lot_detail.html",
        {
            "lot": lot,
            "roasts": roasts,
            "adjustments": adjustments,
            "certifications": "、".join(c.label for c in lot.certifications.all()),
            "can_delete": not roasts.exists() and not adjustments.exists(),
        },
    )


def lot_new(request):
    initial = {}
    copy_from = None
    source_id = request.GET.get("copy")
    if source_id:
        copy_from = GreenLot.objects.filter(pk=source_id).first()
        if copy_from:
            initial = lot_copy_initial(copy_from)
    return _lot_form(request, GreenLot(), initial=initial, copy_from=copy_from)


def lot_edit(request, pk):
    lot = get_object_or_404(GreenLot.objects.with_stock(), pk=pk)
    return _lot_form(request, lot)


def _lot_form(request, lot: GreenLot, *, initial=None, copy_from=None):
    editing = lot.pk is not None
    if request.method == "POST":
        form = GreenLotForm(request.POST, instance=lot)
        if form.is_valid():
            try:
                with transaction.atomic():
                    lot = form.build()
                    if form.cleaned_data["supplier_choice"] == NEW:
                        lot.supplier = Supplier.objects.create(
                            name=form.cleaned_data["new_supplier"].strip()
                        )
                    services.save_green_lot(lot)
                    lot.certifications.set(form.cleaned_data["certifications"])
            except ValidationError as e:
                if not editing:
                    lot.pk = None
                add_service_error(form, e)
            else:
                messages.success(
                    request, "ロットを保存しました" if editing else "仕入れを登録しました"
                )
                return redirect("inventory:lot_detail", pk=lot.pk)
    else:
        form = GreenLotForm(instance=lot, initial=initial)

    suggestions = {
        name: GreenLot.objects.exclude(**{name: ""})
        .order_by(name)
        .values_list(name, flat=True)
        .distinct()
        for name in LOT_SUGGEST_FIELDS
    }
    used_net = 0
    if editing:
        used_net = lot.used_g - lot.adjusted_g
    return render(
        request,
        "inventory/lot_form.html",
        {
            "form": form,
            "lot": lot if editing else None,
            "copy_from": copy_from,
            "copy_sources": GreenLot.objects.order_by("-purchased_on", "-id"),
            "suggestions": suggestions,
            "weight_hint": f"使用済み {used_net:,} g" if used_net > 0 else "例：5、2.5",
            "kg_price": lot_kg_price(form.data)
            if form.is_bound
            else (lot.price_per_kg if editing else None),
            "forms_with_errors": [form] if form.errors else [],
        },
    )


@require_POST
def lot_preview(request):
    """入力中の kg 単価を計算して返す（htmx）。"""
    return render(
        request,
        "inventory/lot_form.html#kg_price",
        {"kg_price": lot_kg_price(request.POST)},
    )


@require_POST
def lot_delete(request, pk):
    lot = get_object_or_404(GreenLot, pk=pk)
    try:
        lot.delete()
    except ProtectedError:
        messages.error(request, "焙煎記録や在庫調整があるロットは削除できません。")
        return redirect("inventory:lot_detail", pk=pk)
    messages.success(request, "ロットを削除しました")
    return redirect("inventory:lot_list")


def lot_previous_roast(lot_id, *, before: Roast | None = None):
    """同じ生豆ロットの前回の焙煎記録（焙煎の入力画面で比べるため）。"""
    roasts = Roast.objects.filter(green_lot_id=lot_id).select_related("coffee")
    if before is not None and before.pk:
        roasts = roasts.exclude(pk=before.pk).filter(roasted_at__lt=before.roasted_at)
    return roasts.order_by("-roasted_at", "-id").first()
