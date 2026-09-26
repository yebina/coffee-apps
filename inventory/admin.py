"""管理画面。問屋と選択肢の編集、データの手直しに使う（architecture.md 5.5）。

在庫が動くモデルの保存・削除は services.py を通し、在庫のチェックをすり抜けないようにする。
販売は明細と引当を一緒に作り直す必要があるので、管理画面では見るだけにする。
"""

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect

from . import calc, services
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
    Supplier,
)


@admin.register(ChoiceOption)
class ChoiceOptionAdmin(admin.ModelAdmin):
    list_display = ["label", "category", "sort_order", "is_active"]
    list_filter = ["category", "is_active"]
    list_editable = ["sort_order", "is_active"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_person", "phone", "email", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]


class ServiceBackedAdmin(admin.ModelAdmin):
    """保存と削除を services.py に任せる。

    在庫が足りないときの StockError は、管理画面のトランザクションを抜けてから受け止める
    （その時点で書き込みは取り消されている）。エラーを表示して、同じ画面に戻す。
    """

    save_service = None
    delete_service = None

    def save_model(self, request, obj, form, change):
        type(self).save_service(obj)

    def delete_model(self, request, obj):
        if type(self).delete_service is None:
            return super().delete_model(request, obj)
        type(self).delete_service(obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)

    def _with_stock_errors(self, request, view, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValidationError as e:
            self.message_user(request, " ".join(e.messages), messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    def changeform_view(self, request, *args, **kwargs):
        return self._with_stock_errors(request, super().changeform_view, *args, **kwargs)

    def delete_view(self, request, *args, **kwargs):
        return self._with_stock_errors(request, super().delete_view, *args, **kwargs)

    def changelist_view(self, request, *args, **kwargs):
        return self._with_stock_errors(request, super().changelist_view, *args, **kwargs)


@admin.register(GreenLot)
class GreenLotAdmin(ServiceBackedAdmin):
    save_service = services.save_green_lot

    list_display = ["name", "purchased_on", "supplier", "country", "weight_g", "remaining_g"]
    list_filter = ["is_active", "supplier", "country"]
    search_fields = ["name", "product_name", "country", "farm"]
    filter_horizontal = ["certifications"]

    def get_queryset(self, request):
        return super().get_queryset(request).with_stock()

    @admin.display(description="残量（g）", ordering="remaining_g")
    def remaining_g(self, obj):
        return obj.remaining_g


@admin.register(Coffee)
class CoffeeAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "remaining_g"]
    list_filter = ["is_active"]

    def get_queryset(self, request):
        return super().get_queryset(request).with_stock()

    @admin.display(description="残量（g）", ordering="remaining_g")
    def remaining_g(self, obj):
        return obj.remaining_g


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["__str__", "price_yen", "packaging_cost_yen", "is_active"]
    list_filter = ["is_active", "coffee"]


@admin.register(Roast)
class RoastAdmin(ServiceBackedAdmin):
    save_service = services.save_roast
    delete_service = services.delete_roast

    list_display = [
        "roasted_at",
        "coffee",
        "green_lot",
        "input_g",
        "output_g",
        "loss_rate_display",
        "duration_display",
        "roast_level",
        "remaining_g",
    ]
    list_filter = ["coffee", "green_lot", "roast_level"]
    list_select_related = ["coffee", "green_lot"]

    def get_queryset(self, request):
        return super().get_queryset(request).with_stock()

    @admin.display(description="ロス率（%）")
    def loss_rate_display(self, obj):
        return calc.display_percent(obj.loss_rate)

    @admin.display(description="焙煎時間")
    def duration_display(self, obj):
        return calc.format_mmss(obj.duration_s)

    @admin.display(description="残量（g）", ordering="remaining_g")
    def remaining_g(self, obj):
        return obj.remaining_g


class AllocationInline(admin.TabularInline):
    model = Allocation
    extra = 0
    can_delete = False
    readonly_fields = ["roast", "weight_g"]


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    can_delete = False
    readonly_fields = ["product", "quantity", "unit_price_yen", "packaging_cost_yen"]


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["sold_on", "channel", "customer"]
    list_filter = ["channel"]
    inlines = [SaleItemInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        services.delete_sale(obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            services.delete_sale(obj)


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ["sale", "product", "quantity", "unit_price_yen"]
    inlines = [AllocationInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Adjustment)
class AdjustmentAdmin(ServiceBackedAdmin):
    save_service = services.save_adjustment
    delete_service = services.delete_adjustment

    list_display = ["adjusted_on", "target", "delta_g", "reason"]
    list_filter = ["reason"]
