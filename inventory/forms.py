"""入力フォーム。入力の形を確かめるところまでを受け持つ。

在庫が足りるかなどの業務ルールは services.py が確かめる（保存するときと同じコード）。
"""

import unicodedata
from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import ChoiceOption, Coffee, GreenLot, Product, Roast, Supplier

NEW = "__new__"  # 「＋ 新しい〜を追加」の選択肢


def normalize_number(value) -> str:
    """全角の数字・記号を半角にし、桁区切りのカンマを取る。"""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return text.replace(",", "").replace("−", "-").replace("‐", "-")


class NumberInputMixin:
    def to_python(self, value):
        return super().to_python(normalize_number(value))


class IntField(NumberInputMixin, forms.IntegerField):
    widget = forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"})


class DecField(NumberInputMixin, forms.DecimalField):
    widget = forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"})


def options(category: str, current=None):
    """使う選択肢。今の値が「使わない」になっていても、編集できるよう残す。"""
    qs = ChoiceOption.objects.filter(category=category)
    if current is not None:
        return qs.filter(is_active=True) | qs.filter(pk=current.pk)
    return qs.filter(is_active=True)


def _parse_min_sec(minutes: str, seconds: str, label: str) -> int | None:
    minutes, seconds = normalize_number(minutes), normalize_number(seconds)
    if not minutes and not seconds:
        return None
    try:
        m = int(minutes or 0)
        s = int(seconds or 0)
    except ValueError:
        raise ValidationError(
            f"{label}は、分と秒を整数で入力してください（秒は 0〜59）。"
        ) from None
    if m < 0 or not 0 <= s <= 59:
        raise ValidationError(f"{label}は、分と秒を整数で入力してください（秒は 0〜59）。")
    return m * 60 + s


class StyledFormMixin:
    """デモの CSS のクラスを、入力欄に付ける。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.RadioSelect | forms.CheckboxSelectMultiple):
                continue
            if isinstance(widget, forms.Select):
                css = "select"
            elif isinstance(widget, forms.Textarea):
                css = (
                    "textarea textarea-sm" if int(widget.attrs.get("rows", 3)) <= 2 else "textarea"
                )
            else:
                css = "input"
                if widget.attrs.get("inputmode") in ("numeric", "decimal"):
                    css += " num"
            widget.attrs["class"] = css
            widget.attrs.setdefault("autocomplete", "off")


# ---------------------------------------------------------------------------
# 生豆ロット
# ---------------------------------------------------------------------------


# 過去に入力した値を候補に出す項目（仕様書 4.2）
LOT_SUGGEST_FIELDS = ["country", "area", "farm", "producer", "variety", "grade", "packaging"]


class GreenLotForm(StyledFormMixin, forms.ModelForm):
    supplier_choice = forms.ChoiceField(label="問屋")
    new_supplier = forms.CharField(label="新しい問屋名", required=False, max_length=200)
    weight_kg = DecField(label="仕入れ重量", min_value=Decimal("0.001"), decimal_places=3)
    price_yen = IntField(label="仕入れ値", min_value=0)
    extra_cost_yen = IntField(label="送料などの経費", min_value=0, required=False)
    cupping_score = DecField(
        label="カッピングスコア", required=False, max_digits=5, decimal_places=2
    )

    class Meta:
        model = GreenLot
        fields = [
            "name",
            "purchased_on",
            "product_name",
            "english_name",
            "product_code",
            "product_url",
            "country",
            "area",
            "farm",
            "producer",
            "variety",
            "process",
            "altitude",
            "crop_year",
            "grade",
            "rank",
            "cupping_profile",
            "cupping_score",
            "certifications",
            "packaging",
            "description",
            "price_yen",
            "extra_cost_yen",
            "memo",
        ]
        widgets = {
            "purchased_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "certifications": forms.CheckboxSelectMultiple,
            "cupping_profile": forms.Textarea(attrs={"rows": 2}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "memo": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        lot = self.instance
        suppliers = Supplier.objects.filter(is_active=True)
        if lot.pk:
            suppliers = suppliers | Supplier.objects.filter(pk=lot.supplier_id)
        self.fields["supplier_choice"].choices = (
            [("", "選んでください")]
            + [(str(s.pk), s.name) for s in suppliers.order_by("name")]
            + [(NEW, "＋ 新しい問屋を追加")]
        )
        self.fields["process"].queryset = options(ChoiceOption.Category.PROCESS, lot.process)
        self.fields["process"].empty_label = "選んでください"
        self.fields["rank"].queryset = options(ChoiceOption.Category.RANK, lot.rank)
        self.fields["rank"].empty_label = "選んでください"
        certs = ChoiceOption.objects.filter(category=ChoiceOption.Category.CERTIFICATION)
        current = list(lot.certifications.all()) if lot.pk else []
        self.fields["certifications"].queryset = certs.filter(is_active=True) | certs.filter(
            pk__in=[c.pk for c in current]
        )
        for name in LOT_SUGGEST_FIELDS:
            self.fields[name].widget.attrs["list"] = f"dl-{name}"
        if lot.pk:
            self.initial.setdefault("supplier_choice", str(lot.supplier_id))
            self.initial.setdefault("weight_kg", Decimal(lot.weight_g) / 1000)
        else:
            self.initial.setdefault("purchased_on", timezone.localdate())

    def clean(self):
        data = super().clean()
        choice = data.get("supplier_choice")
        if choice == NEW:
            if not (data.get("new_supplier") or "").strip():
                self.add_error("new_supplier", "新しい問屋の名前を入力してください。")
        elif choice:
            try:
                data["supplier"] = Supplier.objects.get(pk=choice)
            except (Supplier.DoesNotExist, ValueError):
                self.add_error("supplier_choice", "問屋を選んでください。")
        weight_kg = data.get("weight_kg")
        if weight_kg is not None:
            data["weight_g"] = int((weight_kg * 1000).to_integral_value())
        if data.get("extra_cost_yen") is None:
            data["extra_cost_yen"] = 0
        return data

    def build(self) -> GreenLot:
        """保存する前のロット（新しい問屋はまだ作らない）。"""
        lot = self.instance
        for name in self.Meta.fields:
            if name != "certifications" and name in self.cleaned_data:
                setattr(lot, name, self.cleaned_data[name])
        lot.weight_g = self.cleaned_data["weight_g"]
        if "supplier" in self.cleaned_data:
            lot.supplier = self.cleaned_data["supplier"]
        return lot


def lot_copy_initial(source: GreenLot) -> dict:
    """「この豆をまた仕入れる」：産地と問屋の情報をコピーする。日付・重量・金額・メモは除く。"""
    skip = {"purchased_on", "price_yen", "extra_cost_yen", "memo", "certifications"}
    initial = {name: getattr(source, name) for name in GreenLotForm.Meta.fields if name not in skip}
    initial["process"] = source.process_id
    initial["rank"] = source.rank_id
    initial["certifications"] = list(source.certifications.values_list("pk", flat=True))
    initial["supplier_choice"] = str(source.supplier_id)
    initial["purchased_on"] = timezone.localdate()
    return initial


def lot_kg_price(data) -> Decimal | None:
    """入力中の kg 単価（htmx のプレビュー用）。入力が途中なら None。"""
    try:
        kg = Decimal(normalize_number(data.get("weight_kg")))
        price = int(normalize_number(data.get("price_yen")))
        extra = int(normalize_number(data.get("extra_cost_yen")) or 0)
    except (InvalidOperation, ValueError):
        return None
    if kg <= 0 or price < 0 or extra < 0:
        return None
    return Decimal(price + extra) / kg


# ---------------------------------------------------------------------------
# 焙煎記録
# ---------------------------------------------------------------------------


class RoastForm(StyledFormMixin, forms.ModelForm):
    coffee_choice = forms.ChoiceField(label="銘柄")
    new_coffee = forms.CharField(label="新しい銘柄名", required=False, max_length=200)
    roasted_at = forms.DateTimeField(
        label="焙煎日時",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    input_g = IntField(label="投入量", min_value=1)
    handpick_g = IntField(label="ハンドピックで除いた量", min_value=0, required=False)
    output_g = IntField(label="焙煎後重量", min_value=1)
    duration_m = forms.CharField(label="焙煎時間", required=False)
    duration_sec = forms.CharField(required=False)
    first_m = forms.CharField(label="1ハゼ開始", required=False)
    first_sec = forms.CharField(required=False)
    second_m = forms.CharField(label="2ハゼ開始", required=False)
    second_sec = forms.CharField(required=False)
    rating = forms.TypedChoiceField(
        label="評価",
        choices=[("", "未評価")] + [(str(n), f"{n} / 5") for n in range(1, 6)],
        coerce=int,
        empty_value=None,
        required=False,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Roast
        fields = [
            "roasted_at",
            "green_lot",
            "roaster",
            "input_g",
            "handpick_g",
            "output_g",
            "heat_notes",
            "roast_level",
            "memo",
            "tasting_notes",
            "rating",
            "tasted_on",
        ]
        widgets = {
            "roast_level": forms.RadioSelect,
            "heat_notes": forms.Textarea(attrs={"rows": 2}),
            "memo": forms.Textarea(attrs={"rows": 2}),
            "tasting_notes": forms.Textarea(attrs={"rows": 3}),
            "tasted_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        roast = self.instance
        lots = GreenLot.objects.in_stock()
        if roast.pk:
            lots = GreenLot.objects.with_stock().filter(
                pk__in=list(lots.values_list("pk", flat=True)) + [roast.green_lot_id]
            )
        self.lots = list(lots.order_by("-purchased_on", "-id"))
        self.fields["green_lot"].queryset = GreenLot.objects.filter(
            pk__in=[lot.pk for lot in self.lots]
        )
        self.fields["green_lot"].empty_label = "選んでください"
        coffees = Coffee.objects.filter(is_active=True)
        if roast.pk:
            coffees = coffees | Coffee.objects.filter(pk=roast.coffee_id)
        self.fields["coffee_choice"].choices = (
            [("", "選んでください")]
            + [(str(c.pk), c.name) for c in coffees.order_by("name")]
            + [(NEW, "＋ 新しい銘柄を作る")]
        )
        self.fields["roast_level"].choices = list(Roast.RoastLevel.choices)
        self.fields["roast_level"].required = False
        for name in ("duration", "first", "second"):
            self.fields[f"{name}_m"].widget.attrs.update(inputmode="numeric", placeholder="分")
            self.fields[f"{name}_sec"].widget.attrs.update(inputmode="numeric", placeholder="秒")
        # 販売に使われた焙煎記録は、銘柄を変えられない（送られてきた値は使わない）
        if roast.pk and roast.allocations.exists():
            self.fields["coffee_choice"].disabled = True
        if roast.pk:
            self.initial.setdefault("coffee_choice", str(roast.coffee_id))
            for prefix, value in (
                ("duration", roast.duration_s),
                ("first", roast.first_crack_s),
                ("second", roast.second_crack_s),
            ):
                if value is not None:
                    self.initial.setdefault(f"{prefix}_m", value // 60)
                    self.initial.setdefault(f"{prefix}_sec", value % 60)
        else:
            self.initial.setdefault("roasted_at", timezone.localtime().replace(second=0))
            self.initial.setdefault("handpick_g", 0)
            self.initial.setdefault("roaster", "手回し焙煎機")

    def clean(self):
        data = super().clean()
        if data.get("handpick_g") is None:
            data["handpick_g"] = 0
        choice = data.get("coffee_choice")
        if choice == NEW:
            if not (data.get("new_coffee") or "").strip():
                self.add_error("new_coffee", "新しい銘柄の名前を入力してください。")
            elif Coffee.objects.filter(name=data["new_coffee"].strip()).exists():
                self.add_error(
                    "new_coffee", "同じ名前の銘柄がすでにあります。一覧から選んでください。"
                )
        elif choice:
            try:
                data["coffee"] = Coffee.objects.get(pk=choice)
            except (Coffee.DoesNotExist, ValueError):
                self.add_error("coffee_choice", "銘柄を選んでください。")

        times = {}
        for prefix, label in (
            ("duration", "焙煎時間"),
            ("first", "1ハゼ開始"),
            ("second", "2ハゼ開始"),
        ):
            try:
                times[prefix] = _parse_min_sec(
                    data.get(f"{prefix}_m"), data.get(f"{prefix}_sec"), label
                )
            except ValidationError as e:
                self.add_error(f"{prefix}_m", e)
                times[prefix] = None
        if times["duration"] is None and not self.has_error("duration_m"):
            self.add_error("duration_m", "焙煎時間（投入から排出まで）を入力してください。")
        total, first, second = times["duration"], times["first"], times["second"]
        if total is not None and first is not None and first >= total:
            self.add_error("first_m", "1ハゼ開始は、焙煎時間より前の時間にしてください。")
        if total is not None and second is not None and second >= total:
            self.add_error("second_m", "2ハゼ開始は、焙煎時間より前の時間にしてください。")
        if first is not None and second is not None and second <= first:
            self.add_error("second_m", "2ハゼ開始は、1ハゼ開始より後の時間にしてください。")
        data["duration_s"], data["first_crack_s"], data["second_crack_s"] = total, first, second

        input_g, output_g = data.get("input_g"), data.get("output_g")
        if input_g and output_g and output_g >= input_g:
            self.add_error("output_g", "焙煎後重量は、投入量より少なくしてください。")
        return data

    def _post_clean(self):
        # モデルの検証は services.save_roast で行う（銘柄・時間は clean() で入れるため）
        pass

    def build(self) -> Roast:
        roast = self.instance
        for name in self.Meta.fields:
            if name in self.cleaned_data:
                setattr(roast, name, self.cleaned_data[name])
        roast.roast_level = self.cleaned_data.get("roast_level") or ""
        roast.duration_s = self.cleaned_data["duration_s"]
        roast.first_crack_s = self.cleaned_data["first_crack_s"]
        roast.second_crack_s = self.cleaned_data["second_crack_s"]
        if "coffee" in self.cleaned_data:
            roast.coffee = self.cleaned_data["coffee"]
        return roast


# ---------------------------------------------------------------------------
# 銘柄・商品
# ---------------------------------------------------------------------------


class CoffeeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Coffee
        fields = ["name", "description"]


class ProductForm(StyledFormMixin, forms.ModelForm):
    weight_g = IntField(label="内容量", min_value=1)
    price_yen = IntField(label="販売価格（税抜）", min_value=0)
    packaging_cost_yen = IntField(label="包材費", min_value=0, required=False)

    class Meta:
        model = Product
        fields = ["weight_g", "price_yen", "packaging_cost_yen"]

    def clean_packaging_cost_yen(self):
        return self.cleaned_data.get("packaging_cost_yen") or 0


# ---------------------------------------------------------------------------
# 販売
# ---------------------------------------------------------------------------


class SaleForm(StyledFormMixin, forms.Form):
    sold_on = forms.DateField(
        label="販売日", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    channel = forms.ModelChoiceField(label="販売チャネル", queryset=ChoiceOption.objects.none())
    customer = forms.CharField(label="販売先", required=False, max_length=200)
    memo = forms.CharField(label="メモ", required=False)

    def __init__(self, *args, channel=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["channel"].queryset = options(ChoiceOption.Category.SALES_CHANNEL, channel)
        self.fields["channel"].empty_label = None


class SaleItemForm(StyledFormMixin, forms.Form):
    product = forms.ModelChoiceField(label="商品", queryset=Product.objects.all(), required=False)
    quantity = IntField(label="数量", min_value=1, required=False)
    unit_price_yen = IntField(label="単価（税抜）", min_value=0, required=False)
    # 商品を選び直したら単価を販売価格に戻すため、前に選んでいた商品を覚えておく
    prev_product = forms.CharField(required=False, widget=forms.HiddenInput)

    def is_blank(self) -> bool:
        return not self.cleaned_data.get("product")


SaleItemFormSet = forms.formset_factory(SaleItemForm, extra=0, min_num=0)


# ---------------------------------------------------------------------------
# 在庫調整
# ---------------------------------------------------------------------------


class AdjustmentForm(StyledFormMixin, forms.Form):
    MODE_DELTA = "delta"
    MODE_COUNT = "count"

    target = forms.ChoiceField(label="対象")
    mode = forms.ChoiceField(
        choices=[(MODE_DELTA, "増減量を入力"), (MODE_COUNT, "棚卸し（量った残量を入力）")],
        widget=forms.RadioSelect,
        initial=MODE_DELTA,
    )
    delta_g = IntField(label="増減量", required=False)
    actual_g = IntField(label="実際に量った残量", required=False, min_value=0)
    adjusted_on = forms.DateField(
        label="日付", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    reason = forms.ModelChoiceField(label="理由", queryset=ChoiceOption.objects.none())
    memo = forms.CharField(label="メモ", required=False)

    def __init__(self, *args, target_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].choices = [("", "選んでください"), *target_choices]
        self.fields["reason"].queryset = options(ChoiceOption.Category.ADJUSTMENT_REASON)
        self.fields["reason"].empty_label = None
        self.initial.setdefault("adjusted_on", timezone.localdate())

    def clean(self):
        data = super().clean()
        if data.get("mode") == self.MODE_COUNT:
            if data.get("actual_g") is None and not self.has_error("actual_g"):
                self.add_error(
                    "actual_g", "実際に量った残量を、0 以上の整数（g）で入力してください。"
                )
        elif not data.get("delta_g") and not self.has_error("delta_g"):
            self.add_error(
                "delta_g", "増減量を g の整数で入力してください（減ったときはマイナス。例：-50）。"
            )
        return data

    def target_object(self):
        kind, _, pk = (self.cleaned_data.get("target") or "").partition(":")
        model = {"lot": GreenLot, "roast": Roast}.get(kind)
        if model is None:
            return None
        return model.objects.filter(pk=pk).first()
