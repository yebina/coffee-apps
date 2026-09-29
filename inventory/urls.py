from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.home, name="home"),
    path("menu/", views.menu, name="menu"),
    # 生豆ロット
    path("lots/", views.lot_list, name="lot_list"),
    path("lots/new/", views.lot_new, name="lot_new"),
    path("lots/preview/", views.lot_preview, name="lot_preview"),
    path("lots/<int:pk>/", views.lot_detail, name="lot_detail"),
    path("lots/<int:pk>/edit/", views.lot_edit, name="lot_edit"),
    path("lots/<int:pk>/delete/", views.lot_delete, name="lot_delete"),
    # 焙煎記録
    path("roasts/", views.roast_list, name="roast_list"),
    path("roasts/new/", views.roast_new, name="roast_new"),
    path("roasts/preview/", views.roast_preview, name="roast_preview"),
    path("roasts/<int:pk>/", views.roast_detail, name="roast_detail"),
    path("roasts/<int:pk>/edit/", views.roast_edit, name="roast_edit"),
    path("roasts/<int:pk>/delete/", views.roast_delete, name="roast_delete"),
    # 銘柄・商品
    path("coffees/", views.coffee_list, name="coffee_list"),
    path("coffees/new/", views.coffee_create, name="coffee_create"),
    path("coffees/<int:pk>/toggle/", views.coffee_toggle, name="coffee_toggle"),
    path("coffees/<int:pk>/products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/toggle/", views.product_toggle, name="product_toggle"),
    # 販売
    path("sales/", views.sale_list, name="sale_list"),
    path("sales/new/", views.sale_new, name="sale_new"),
    path("sales/preview/", views.sale_preview, name="sale_preview"),
    path("sales/<int:pk>/", views.sale_detail, name="sale_detail"),
    path("sales/<int:pk>/edit/", views.sale_edit, name="sale_edit"),
    path("sales/<int:pk>/delete/", views.sale_delete, name="sale_delete"),
    # 在庫調整
    path("adjust/", views.adjust, name="adjust"),
    path("adjust/preview/", views.adjust_preview, name="adjust_preview"),
    path("adjust/<int:pk>/delete/", views.adjust_delete, name="adjust_delete"),
    # 集計
    path("reports/", views.report, name="report"),
]
