"""在庫管理のテーブル（仕様書「2.2」「4」、architecture.md「5.2」）。

- 重さは g、金額は円（税抜）、時間は秒の整数で保存する。
- 残量・kg 単価・原価などの計算で出す値は保存しない。計算は calc.py と、
  このファイルの QuerySet のメソッドで行う。
- 在庫が動く保存・修正・削除は、必ず services.py を通す。
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import calc


class TimeStamped(models.Model):
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# 選択肢（仕様書 4.9）
# ---------------------------------------------------------------------------


class ChoiceOption(TimeStamped):
    class Category(models.TextChoices):
        SALES_CHANNEL = "sales_channel", "販売チャネル"
        PROCESS = "process", "生産処理"
        RANK = "rank", "ランク"
        CERTIFICATION = "certification", "認証・受賞"
        ADJUSTMENT_REASON = "adjustment_reason", "在庫調整の理由"

    category = models.CharField("種類", max_length=32, choices=Category.choices)
    label = models.CharField("表示名", max_length=100)
    sort_order = models.PositiveIntegerField("並び順", default=0)
    is_active = models.BooleanField("使う", default=True)

    class Meta:
        verbose_name = verbose_name_plural = "選択肢"
        ordering = ["category", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["category", "label"], name="choice_unique_label"),
        ]

    def __str__(self) -> str:
        return self.label


def _choices(category: str) -> dict:
    return {"category": category}


# ---------------------------------------------------------------------------
# 問屋（仕様書 4.1）
# ---------------------------------------------------------------------------


class Supplier(TimeStamped):
    name = models.CharField("問屋名", max_length=200)
    contact_person = models.CharField("担当者", max_length=100, blank=True)
    phone = models.CharField("電話番号", max_length=50, blank=True)
    email = models.EmailField("メール", blank=True)
    website = models.URLField("Web サイト", blank=True)
    memo = models.TextField("メモ", blank=True)
    is_active = models.BooleanField("使う", default=True)

    class Meta:
        verbose_name = verbose_name_plural = "問屋"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# 生豆ロット（仕様書 4.2）
# ---------------------------------------------------------------------------


class GreenLotQuerySet(models.QuerySet):
    def with_stock(self):
        """used_g（生豆使用量の合計）、adjusted_g（在庫調整の合計）、remaining_g（残量）を付ける。"""
        roasts = Roast.objects.filter(green_lot=OuterRef("pk"))
        used = (
            roasts.order_by()
            .values("green_lot")
            .annotate(_t=Sum(F("input_g") + F("handpick_g")))
            .values("_t")
        )
        adjusted = (
            Adjustment.objects.filter(green_lot=OuterRef("pk"))
            .order_by()
            .values("green_lot")
            .annotate(_t=Sum("delta_g"))
            .values("_t")
        )
        return self.annotate(
            used_g=Coalesce(Subquery(used[:1], output_field=models.IntegerField()), Value(0)),
            adjusted_g=Coalesce(
                Subquery(adjusted[:1], output_field=models.IntegerField()), Value(0)
            ),
        ).annotate(remaining_g=F("weight_g") - F("used_g") + F("adjusted_g"))

    def in_stock(self):
        return self.with_stock().filter(remaining_g__gt=0)


class GreenLot(TimeStamped):
    # 基本
    name = models.CharField("ロット名", max_length=200)
    purchased_on = models.DateField("仕入れ日")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="green_lots", verbose_name="問屋"
    )
    product_name = models.CharField("問屋の商品名", max_length=300, blank=True)
    english_name = models.CharField("英文名", max_length=300, blank=True)
    product_code = models.CharField("商品コード", max_length=100, blank=True)
    product_url = models.URLField("商品ページの URL", max_length=500, blank=True)
    # 産地
    country = models.CharField("国", max_length=100)
    area = models.CharField("エリア", max_length=300, blank=True)
    farm = models.CharField("農園名", max_length=200, blank=True)
    producer = models.CharField("生産者", max_length=200, blank=True)
    variety = models.CharField("品種", max_length=200, blank=True)
    process = models.ForeignKey(
        ChoiceOption,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to=_choices(ChoiceOption.Category.PROCESS),
        verbose_name="生産処理（精製方法）",
    )
    altitude = models.CharField("標高", max_length=100, blank=True)
    crop_year = models.CharField("収穫年度", max_length=20, blank=True)
    grade = models.CharField("等級", max_length=50, blank=True)
    # 問屋の情報
    rank = models.ForeignKey(
        ChoiceOption,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to=_choices(ChoiceOption.Category.RANK),
        verbose_name="ランク",
    )
    cupping_profile = models.TextField("カッピングプロファイル", blank=True)
    cupping_score = models.DecimalField(
        "カッピングスコア", max_digits=5, decimal_places=2, null=True, blank=True
    )
    certifications = models.ManyToManyField(
        ChoiceOption,
        blank=True,
        related_name="+",
        limit_choices_to=_choices(ChoiceOption.Category.CERTIFICATION),
        verbose_name="認証・受賞",
    )
    packaging = models.CharField("包装", max_length=100, blank=True)
    description = models.TextField("商品説明・備考", blank=True)
    # 数量・金額
    weight_g = models.PositiveIntegerField("仕入れ重量（g）")
    price_yen = models.PositiveIntegerField("仕入れ値（円・税抜）")
    extra_cost_yen = models.PositiveIntegerField("送料などの経費（円・税抜）", default=0)
    # その他
    memo = models.TextField("メモ", blank=True)
    is_active = models.BooleanField("表示する", default=True)

    objects = GreenLotQuerySet.as_manager()

    class Meta:
        verbose_name = verbose_name_plural = "生豆ロット"
        ordering = ["-purchased_on", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(weight_g__gt=0), name="green_lot_weight_positive"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def total_cost_yen(self) -> int:
        return self.price_yen + self.extra_cost_yen

    @property
    def price_per_kg(self) -> Decimal:
        return calc.green_price_per_kg(self.price_yen, self.extra_cost_yen, self.weight_g)

    @property
    def price_per_g(self) -> Decimal:
        return calc.green_price_per_g(self.price_yen, self.extra_cost_yen, self.weight_g)

    def remaining(self) -> int:
        """残量（g）。一覧では with_stock() を使う。"""
        return GreenLot.objects.with_stock().get(pk=self.pk).remaining_g


# ---------------------------------------------------------------------------
# 銘柄・商品（仕様書 4.3）
# ---------------------------------------------------------------------------


class CoffeeQuerySet(models.QuerySet):
    def with_stock(self):
        """remaining_g（焙煎豆の残量）を付ける。"""
        remaining = (
            Roast.objects.with_stock()
            .filter(coffee=OuterRef("pk"))
            .order_by()
            .values("coffee")
            .annotate(_t=Sum("remaining_g"))
            .values("_t")
        )
        return self.annotate(
            remaining_g=Coalesce(
                Subquery(remaining[:1], output_field=models.IntegerField()), Value(0)
            )
        )


class Coffee(TimeStamped):
    name = models.CharField("銘柄名", max_length=200, unique=True)
    description = models.TextField("説明文", blank=True)
    is_active = models.BooleanField("販売中", default=True)

    objects = CoffeeQuerySet.as_manager()

    class Meta:
        verbose_name = verbose_name_plural = "銘柄"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def remaining(self) -> int:
        return Coffee.objects.with_stock().get(pk=self.pk).remaining_g


class Product(TimeStamped):
    coffee = models.ForeignKey(
        Coffee, on_delete=models.PROTECT, related_name="products", verbose_name="銘柄"
    )
    weight_g = models.PositiveIntegerField("内容量（g）")
    price_yen = models.PositiveIntegerField("販売価格（円・税抜）")
    packaging_cost_yen = models.PositiveIntegerField("包材費（円・税抜）", default=0)
    is_active = models.BooleanField("販売中", default=True)

    class Meta:
        verbose_name = verbose_name_plural = "商品"
        ordering = ["coffee__name", "weight_g"]
        constraints = [
            models.CheckConstraint(condition=Q(weight_g__gte=1), name="product_weight_positive"),
            models.UniqueConstraint(fields=["coffee", "weight_g"], name="product_unique_weight"),
        ]

    def __str__(self) -> str:
        return f"{self.coffee.name} {self.weight_g}g"


# ---------------------------------------------------------------------------
# 焙煎記録（仕様書 4.4）
# ---------------------------------------------------------------------------


class RoastQuerySet(models.QuerySet):
    def with_stock(self):
        """allocated_g（引当の合計）、adjusted_g（在庫調整の合計）、remaining_g（残量）を付ける。"""
        allocated = (
            Allocation.objects.filter(roast=OuterRef("pk"))
            .order_by()
            .values("roast")
            .annotate(_t=Sum("weight_g"))
            .values("_t")
        )
        adjusted = (
            Adjustment.objects.filter(roast=OuterRef("pk"))
            .order_by()
            .values("roast")
            .annotate(_t=Sum("delta_g"))
            .values("_t")
        )
        return self.annotate(
            allocated_g=Coalesce(
                Subquery(allocated[:1], output_field=models.IntegerField()), Value(0)
            ),
            adjusted_g=Coalesce(
                Subquery(adjusted[:1], output_field=models.IntegerField()), Value(0)
            ),
        ).annotate(remaining_g=F("output_g") - F("allocated_g") + F("adjusted_g"))


class Roast(TimeStamped):
    class RoastLevel(models.TextChoices):
        LIGHT = "light", "ライト"
        CINNAMON = "cinnamon", "シナモン"
        MEDIUM = "medium", "ミディアム"
        HIGH = "high", "ハイ"
        CITY = "city", "シティ"
        FULL_CITY = "full_city", "フルシティ"
        FRENCH = "french", "フレンチ"
        ITALIAN = "italian", "イタリアン"

    # 基本
    roasted_at = models.DateTimeField("焙煎日時", default=timezone.now)
    green_lot = models.ForeignKey(
        GreenLot, on_delete=models.PROTECT, related_name="roasts", verbose_name="生豆ロット"
    )
    coffee = models.ForeignKey(
        Coffee, on_delete=models.PROTECT, related_name="roasts", verbose_name="銘柄"
    )
    roaster = models.CharField("焙煎機", max_length=100, default="手回し焙煎機", blank=True)
    # 重量
    input_g = models.PositiveIntegerField("投入量（g）")
    handpick_g = models.PositiveIntegerField("ハンドピックで除いた量（g）", default=0)
    output_g = models.PositiveIntegerField("焙煎後重量（g）")
    # プロファイル（投入からの秒数）
    duration_s = models.PositiveIntegerField("焙煎時間（秒）")
    first_crack_s = models.PositiveIntegerField("1ハゼ開始（秒）", null=True, blank=True)
    second_crack_s = models.PositiveIntegerField("2ハゼ開始（秒）", null=True, blank=True)
    heat_notes = models.TextField("火力・操作のメモ", blank=True)
    roast_level = models.CharField("焙煎度", max_length=20, choices=RoastLevel.choices, blank=True)
    memo = models.TextField("メモ", blank=True)
    # 焙煎後の特徴
    tasting_notes = models.TextField("特徴", blank=True)
    rating = models.PositiveSmallIntegerField(
        "評価",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    tasted_on = models.DateField("試飲日", null=True, blank=True)
    # 二重送信の防止（architecture.md 5.4）
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    objects = RoastQuerySet.as_manager()

    class Meta:
        verbose_name = verbose_name_plural = "焙煎記録"
        ordering = ["-roasted_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(input_g__gt=0), name="roast_input_positive"),
            models.CheckConstraint(condition=Q(output_g__gt=0), name="roast_output_positive"),
            models.CheckConstraint(
                condition=Q(output_g__lt=F("input_g")), name="roast_output_lt_input"
            ),
            models.CheckConstraint(condition=Q(duration_s__gt=0), name="roast_duration_positive"),
            models.CheckConstraint(
                condition=Q(first_crack_s__isnull=True) | Q(first_crack_s__lt=F("duration_s")),
                name="roast_first_crack_lt_duration",
            ),
            models.CheckConstraint(
                condition=Q(second_crack_s__isnull=True) | Q(second_crack_s__lt=F("duration_s")),
                name="roast_second_crack_lt_duration",
            ),
            models.CheckConstraint(
                condition=Q(first_crack_s__isnull=True)
                | Q(second_crack_s__isnull=True)
                | Q(first_crack_s__lt=F("second_crack_s")),
                name="roast_first_crack_lt_second",
            ),
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5),
                name="roast_rating_range",
            ),
        ]

    def __str__(self) -> str:
        local = timezone.localtime(self.roasted_at)
        return f"{local:%Y-%m-%d %H:%M} {self.coffee.name}"

    @property
    def green_used_g(self) -> int:
        return calc.green_used_g(self.input_g, self.handpick_g)

    @property
    def loss_rate(self) -> Decimal:
        return calc.loss_rate(self.input_g, self.output_g)

    @property
    def cost_yen(self) -> Decimal:
        lot = self.green_lot
        return calc.roast_cost(self.green_used_g, lot.price_per_g)

    @property
    def cost_per_g(self) -> Decimal:
        return calc.roast_cost_per_g(self.cost_yen, self.output_g)

    @property
    def development_s(self) -> int | None:
        return calc.development_time_s(self.duration_s, self.first_crack_s)

    @property
    def development_ratio(self) -> Decimal | None:
        return calc.development_ratio(self.duration_s, self.first_crack_s)

    def remaining(self) -> int:
        return Roast.objects.with_stock().get(pk=self.pk).remaining_g


# ---------------------------------------------------------------------------
# 販売（仕様書 4.5）
# ---------------------------------------------------------------------------


class Sale(TimeStamped):
    sold_on = models.DateField("販売日", default=timezone.localdate)
    channel = models.ForeignKey(
        ChoiceOption,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to=_choices(ChoiceOption.Category.SALES_CHANNEL),
        verbose_name="販売チャネル",
    )
    customer = models.CharField("販売先", max_length=200, blank=True)
    memo = models.TextField("メモ", blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = "販売"
        ordering = ["-sold_on", "-id"]

    def __str__(self) -> str:
        return f"{self.sold_on} {self.channel.label}"

    @property
    def amount_yen(self) -> int:
        return sum(item.amount_yen for item in self.items.all())

    @property
    def cost_yen(self) -> Decimal:
        return sum((item.cost_yen for item in self.items.all()), Decimal(0))

    @property
    def gross_profit_yen(self) -> Decimal:
        return calc.gross_profit(self.amount_yen, self.cost_yen)


class SaleItem(TimeStamped):
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="items", verbose_name="販売"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="sale_items", verbose_name="商品"
    )
    quantity = models.PositiveIntegerField("数量")
    # 販売したときの値を残す。あとで商品の価格や包材費を変えても、過去の販売は変わらない
    unit_price_yen = models.PositiveIntegerField("単価（円・税抜）")
    packaging_cost_yen = models.PositiveIntegerField("包材費（円・税抜）", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "販売明細"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="sale_item_quantity_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} × {self.quantity}"

    @property
    def weight_g(self) -> int:
        return self.product.weight_g * self.quantity

    @property
    def amount_yen(self) -> int:
        return calc.line_amount(self.unit_price_yen, self.quantity)

    @property
    def cost_yen(self) -> Decimal:
        allocations = [(a.weight_g, a.roast.cost_per_g) for a in self.allocations.all()]
        return calc.sale_item_cost(allocations, self.packaging_cost_yen, self.quantity)

    @property
    def gross_profit_yen(self) -> Decimal:
        return calc.gross_profit(self.amount_yen, self.cost_yen)


class Allocation(TimeStamped):
    """販売明細の重さを、どの焙煎記録の在庫から出したか。"""

    sale_item = models.ForeignKey(
        SaleItem, on_delete=models.CASCADE, related_name="allocations", verbose_name="販売明細"
    )
    roast = models.ForeignKey(
        Roast, on_delete=models.PROTECT, related_name="allocations", verbose_name="焙煎記録"
    )
    weight_g = models.PositiveIntegerField("重さ（g）")

    class Meta:
        verbose_name = verbose_name_plural = "引当"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(weight_g__gte=1), name="allocation_weight_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.roast} から {self.weight_g}g"


# ---------------------------------------------------------------------------
# 在庫調整（仕様書 4.6）
# ---------------------------------------------------------------------------


class Adjustment(TimeStamped):
    adjusted_on = models.DateField("日付", default=timezone.localdate)
    green_lot = models.ForeignKey(
        GreenLot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="adjustments",
        verbose_name="生豆ロット",
    )
    roast = models.ForeignKey(
        Roast,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="adjustments",
        verbose_name="焙煎記録",
    )
    delta_g = models.IntegerField("増減量（g）")
    reason = models.ForeignKey(
        ChoiceOption,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to=_choices(ChoiceOption.Category.ADJUSTMENT_REASON),
        verbose_name="理由",
    )
    memo = models.TextField("メモ", blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = "在庫調整"
        ordering = ["-adjusted_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(green_lot__isnull=False) & Q(roast__isnull=True))
                | (Q(green_lot__isnull=True) & Q(roast__isnull=False)),
                name="adjustment_exactly_one_target",
            ),
            models.CheckConstraint(condition=~Q(delta_g=0), name="adjustment_delta_nonzero"),
        ]

    def __str__(self) -> str:
        return f"{self.adjusted_on} {self.target} {self.delta_g:+d}g"

    @property
    def target(self):
        return self.green_lot or self.roast
