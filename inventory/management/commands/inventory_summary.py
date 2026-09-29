"""件数と在庫の合計を表示する。バックアップから戻したあと、元の DB と比べるために使う。"""

from django.core.management.base import BaseCommand
from django.db.models import Sum

from inventory.models import (
    Adjustment,
    Allocation,
    Coffee,
    GreenLot,
    Product,
    Roast,
    Sale,
    SaleItem,
    Supplier,
)


class Command(BaseCommand):
    help = "件数と在庫の合計を表示する（バックアップから戻したときの確認用）"

    def handle(self, *args, **options):
        for model in (
            Supplier,
            GreenLot,
            Coffee,
            Product,
            Roast,
            Sale,
            SaleItem,
            Allocation,
            Adjustment,
        ):
            self.stdout.write(f"{model._meta.verbose_name}: {model.objects.count()}")
        green = GreenLot.objects.with_stock().aggregate(g=Sum("remaining_g"))["g"] or 0
        roasted = Roast.objects.with_stock().aggregate(g=Sum("remaining_g"))["g"] or 0
        sales = sum(item.amount_yen for item in SaleItem.objects.all())
        self.stdout.write(f"生豆の残量の合計: {green:,} g")
        self.stdout.write(f"焙煎豆の残量の合計: {roasted:,} g")
        self.stdout.write(f"売上の合計（税抜）: {sales:,} 円")
        last = Sale.objects.order_by("-sold_on").values_list("sold_on", flat=True).first()
        self.stdout.write(f"最後の販売日: {last or '—'}")
