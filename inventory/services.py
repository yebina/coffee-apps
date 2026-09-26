"""在庫を動かす処理（焙煎・販売・在庫調整）。architecture.md「5.4」。

画面の処理（views.py）は在庫を直接書き換えず、必ずここを通す。
在庫が減りうる処理は、すべて次の手順にする。

1. トランザクションを始める
2. 在庫の持ち主の行をロックする。順番は「記録の行（焙煎記録・販売・在庫調整）→ 生豆ロット → 銘柄」、
   同じ種類は ID の小さい順（お互いのロックを待ち続けないようにする）
3. ロックを取ったあとで残量を計算し、足りるか確かめる。足りなければ何も書かずに終える
4. 書き込んで、コミットする
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from . import calc
from .models import (
    Adjustment,
    Allocation,
    ChoiceOption,
    Coffee,
    GreenLot,
    Product,
    Roast,
    Sale,
    SaleItem,
)


class StockError(ValidationError):
    """在庫が足りない、またはすでに使った量より少なくする修正。"""


def _lock(model, ids: Iterable[int | None]) -> dict:
    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    rows = model.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    return {row.pk: row for row in rows}


def _green_remaining(lot_id: int) -> int:
    return GreenLot.objects.with_stock().get(pk=lot_id).remaining_g


def _roast_remaining(roast_id: int) -> int:
    return Roast.objects.with_stock().get(pk=roast_id).remaining_g


# ---------------------------------------------------------------------------
# 生豆ロット
# ---------------------------------------------------------------------------


@transaction.atomic
def save_green_lot(lot: GreenLot) -> GreenLot:
    """生豆ロットを保存する。仕入れ重量を減らすときは、使った量を下回らないか確かめる。"""
    lot.full_clean()
    if lot.pk is None:
        lot.save()
        return lot

    _lock(GreenLot, [lot.pk])
    old_weight = GreenLot.objects.values_list("weight_g", flat=True).get(pk=lot.pk)
    if lot.weight_g < old_weight:
        remaining_after = _green_remaining(lot.pk) - (old_weight - lot.weight_g)
        if remaining_after < 0:
            raise StockError(
                f"仕入れ重量を {lot.weight_g}g にすると、残量が {remaining_after}g になります。"
                "焙煎や在庫調整ですでに使った量より少なくはできません。"
            )
    lot.save()
    return lot


# ---------------------------------------------------------------------------
# 焙煎記録
# ---------------------------------------------------------------------------


@transaction.atomic
def save_roast(roast: Roast, *, idempotency_key: UUID | None = None) -> Roast:
    """焙煎記録を登録・修正する。生豆ロットの残量が減り、銘柄の在庫が増える。"""
    creating = roast.pk is None
    old = None
    if not creating:
        old = Roast.objects.select_for_update().get(pk=roast.pk)
    elif idempotency_key is not None:
        roast.idempotency_key = idempotency_key

    _lock(GreenLot, [roast.green_lot_id, old and old.green_lot_id])
    _lock(Coffee, [roast.coffee_id, old and old.coffee_id])

    if creating and idempotency_key is not None:
        existing = Roast.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    roast.full_clean(exclude=["idempotency_key"])

    # 生豆ロットの残量（仕様書 6：生豆使用量が残量より多いと保存できない）
    new_used = roast.green_used_g
    give_back = old.green_used_g if old and old.green_lot_id == roast.green_lot_id else 0
    available = _green_remaining(roast.green_lot_id) + give_back
    if new_used > available:
        raise StockError(
            f"生豆ロットの残量が足りません（使える量 {available}g、生豆使用量 {new_used}g）。"
        )

    if old is not None:
        stock = Roast.objects.with_stock().get(pk=old.pk)
        used_elsewhere = stock.allocated_g - stock.adjusted_g
        if roast.coffee_id != old.coffee_id and (stock.allocated_g or stock.adjusted_g):
            raise StockError("販売や在庫調整に使われた焙煎記録は、銘柄を変えられません。")
        # 仕様書 6：すでに使った量より少なくする修正はできない
        if roast.output_g < used_elsewhere:
            raise StockError(
                f"焙煎後重量を {roast.output_g}g にはできません。"
                f"すでに {used_elsewhere}g を販売・在庫調整で使っています。"
            )

    roast.save()
    return roast


@transaction.atomic
def delete_roast(roast: Roast) -> None:
    Roast.objects.select_for_update().get(pk=roast.pk)
    if roast.allocations.exists() or roast.adjustments.exists():
        raise StockError("販売や在庫調整に使われた焙煎記録は削除できません。")
    roast.delete()


# ---------------------------------------------------------------------------
# 販売と引当
# ---------------------------------------------------------------------------


@dataclass
class SaleLine:
    product: Product
    quantity: int
    unit_price_yen: int | None = None  # 省略したら商品の販売価格

    @property
    def weight_g(self) -> int:
        return self.product.weight_g * self.quantity

    @property
    def price(self) -> int:
        return self.product.price_yen if self.unit_price_yen is None else self.unit_price_yen


@dataclass
class PlannedAllocation:
    roast: Roast
    weight_g: int


def plan_allocations(
    lines: Sequence[SaleLine], *, exclude_sale: Sale | None = None
) -> list[list[PlannedAllocation]]:
    """明細ごとに、焙煎日の古い焙煎記録から順に引き当てる（先入れ先出し）。保存はしない。

    販売を修正するときの試算では、exclude_sale の引当は無かったものとして数える。
    在庫が足りなければ StockError を出す。
    """
    coffee_ids = {line.product.coffee_id for line in lines}
    roasts = list(
        Roast.objects.with_stock()
        .filter(coffee_id__in=coffee_ids)
        .select_related("coffee", "green_lot")
        .order_by("roasted_at", "id")
    )
    remaining = {r.pk: r.remaining_g for r in roasts}
    if exclude_sale is not None and exclude_sale.pk:
        for alloc in Allocation.objects.filter(sale_item__sale=exclude_sale):
            if alloc.roast_id in remaining:
                remaining[alloc.roast_id] += alloc.weight_g

    by_coffee: dict[int, list[Roast]] = defaultdict(list)
    for r in roasts:
        by_coffee[r.coffee_id].append(r)

    shortages: list[str] = []
    plan: list[list[PlannedAllocation]] = []
    for line in lines:
        need = line.weight_g
        allocations: list[PlannedAllocation] = []
        for r in by_coffee[line.product.coffee_id]:
            if need == 0:
                break
            take = min(need, remaining[r.pk])
            if take <= 0:
                continue
            allocations.append(PlannedAllocation(r, take))
            remaining[r.pk] -= take
            need -= take
        if need:
            shortages.append(f"{line.product}：{need}g 足りません")
        plan.append(allocations)

    if shortages:
        raise StockError(
            "焙煎豆の在庫が足りません（先に焙煎記録か在庫調整を入れてください）。"
            + " ".join(shortages)
        )
    return plan


@transaction.atomic
def save_sale(
    sale: Sale, lines: Sequence[SaleLine], *, idempotency_key: UUID | None = None
) -> Sale:
    """販売を登録・修正する。修正のときは、その販売の引当だけをやり直す（仕様書 6）。"""
    if not lines:
        raise ValidationError("明細を1行以上入力してください。")
    for line in lines:
        if line.quantity < 1:
            raise ValidationError("数量は 1 以上にしてください。")

    creating = sale.pk is None
    if not creating:
        Sale.objects.select_for_update().get(pk=sale.pk)
    elif idempotency_key is not None:
        sale.idempotency_key = idempotency_key

    _lock(Coffee, [line.product.coffee_id for line in lines])

    if creating and idempotency_key is not None:
        existing = Sale.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    sale.full_clean(exclude=["idempotency_key"])
    plan = plan_allocations(lines, exclude_sale=None if creating else sale)

    sale.save()
    if not creating:
        sale.items.all().delete()  # 引当も一緒に消える
    for line, allocations in zip(lines, plan, strict=True):
        item = SaleItem.objects.create(
            sale=sale,
            product=line.product,
            quantity=line.quantity,
            unit_price_yen=line.price,
            packaging_cost_yen=line.product.packaging_cost_yen,
        )
        Allocation.objects.bulk_create(
            Allocation(sale_item=item, roast=a.roast, weight_g=a.weight_g) for a in allocations
        )
    return sale


@transaction.atomic
def delete_sale(sale: Sale) -> None:
    Sale.objects.select_for_update().get(pk=sale.pk)
    sale.delete()


# ---------------------------------------------------------------------------
# 在庫調整
# ---------------------------------------------------------------------------


def _check_targets(green_lot_ids: Iterable[int], roast_ids: Iterable[int]) -> None:
    """書き込んだあとで、残量がマイナスになった対象がないか確かめる。"""
    for lot in GreenLot.objects.with_stock().filter(pk__in=set(green_lot_ids)):
        if lot.remaining_g < 0:
            raise StockError(f"{lot} の残量が {lot.remaining_g}g になります。")
    for roast in Roast.objects.with_stock().filter(pk__in=set(roast_ids)):
        if roast.remaining_g < 0:
            raise StockError(f"{roast} の残量が {roast.remaining_g}g になります。")


def _lock_for_adjustment(*adjustments: Adjustment | None) -> tuple[set[int], set[int]]:
    adjustments = [a for a in adjustments if a is not None]
    lot_ids = {a.green_lot_id for a in adjustments if a.green_lot_id}
    roast_ids = {a.roast_id for a in adjustments if a.roast_id}
    coffee_ids = set(Roast.objects.filter(pk__in=roast_ids).values_list("coffee_id", flat=True))
    _lock(GreenLot, lot_ids)
    _lock(Coffee, coffee_ids)
    return lot_ids, roast_ids


@transaction.atomic
def save_adjustment(adjustment: Adjustment, *, idempotency_key: UUID | None = None) -> Adjustment:
    """在庫調整を登録・修正する。残量がマイナスになる調整はできない（仕様書 6）。"""
    creating = adjustment.pk is None
    old = None
    if not creating:
        old = Adjustment.objects.select_for_update().get(pk=adjustment.pk)
    elif idempotency_key is not None:
        adjustment.idempotency_key = idempotency_key

    lot_ids, roast_ids = _lock_for_adjustment(adjustment, old)

    if creating and idempotency_key is not None:
        existing = Adjustment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    adjustment.full_clean(exclude=["idempotency_key"])
    # 書き込んだあとで確かめる。足りなければ例外でトランザクションごと取り消される
    adjustment.save()
    try:
        _check_targets(lot_ids, roast_ids)
    except StockError:
        if creating:
            adjustment.pk = None
        raise
    return adjustment


@transaction.atomic
def delete_adjustment(adjustment: Adjustment) -> None:
    Adjustment.objects.select_for_update().get(pk=adjustment.pk)
    lot_ids, roast_ids = _lock_for_adjustment(adjustment)
    pk = adjustment.pk
    adjustment.delete()
    try:
        _check_targets(lot_ids, roast_ids)
    except StockError:
        adjustment.pk = pk
        raise


@transaction.atomic
def record_stocktake(
    *,
    target: GreenLot | Roast,
    actual_g: int,
    reason: ChoiceOption,
    adjusted_on=None,
    memo: str = "",
    idempotency_key: UUID | None = None,
) -> Adjustment | None:
    """棚卸し：実際に量った残量との差を、在庫調整として記録する。差がなければ何もしない。"""
    if actual_g < 0:
        raise ValidationError("実際の残量は 0 以上にしてください。")
    probe = Adjustment(
        green_lot=target if isinstance(target, GreenLot) else None,
        roast=target if isinstance(target, Roast) else None,
    )
    _lock_for_adjustment(probe)

    if idempotency_key is not None:
        existing = Adjustment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    if isinstance(target, GreenLot):
        current = _green_remaining(target.pk)
    else:
        current = _roast_remaining(target.pk)
    delta = actual_g - current
    if delta == 0:
        return None

    probe.delta_g = delta
    probe.reason = reason
    probe.memo = memo
    if adjusted_on is not None:
        probe.adjusted_on = adjusted_on
    probe.idempotency_key = idempotency_key
    probe.full_clean(exclude=["idempotency_key"])
    probe.save()
    return probe


# ---------------------------------------------------------------------------
# 入力の確認（保存は止めない）
# ---------------------------------------------------------------------------

LOSS_RATE_WARN_MIN = Decimal("0.05")
LOSS_RATE_WARN_MAX = Decimal("0.30")


def loss_rate_warning(input_g: int, output_g: int) -> str | None:
    """ロス率が 5〜30% の範囲外なら、入力ミスでないか確認する文言を返す（仕様書 6）。"""
    if input_g <= 0 or output_g >= input_g:
        return None
    rate = calc.loss_rate(input_g, output_g)
    if LOSS_RATE_WARN_MIN <= rate <= LOSS_RATE_WARN_MAX:
        return None
    return (
        f"ロス率が {calc.display_percent(rate)}% です。"
        "投入量と焙煎後重量に入力ミスがないか確かめてください。"
    )
