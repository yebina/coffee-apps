from .adjustments import adjust, adjust_delete, adjust_preview
from .coffees import (
    coffee_create,
    coffee_list,
    coffee_toggle,
    product_create,
    product_toggle,
)
from .home import home, menu
from .lots import lot_delete, lot_detail, lot_edit, lot_list, lot_new, lot_preview
from .reports import report
from .roasts import roast_delete, roast_detail, roast_edit, roast_list, roast_new, roast_preview
from .sales import sale_delete, sale_detail, sale_edit, sale_list, sale_new, sale_preview

__all__ = [
    "adjust",
    "adjust_delete",
    "adjust_preview",
    "coffee_create",
    "coffee_list",
    "coffee_toggle",
    "home",
    "lot_delete",
    "lot_detail",
    "lot_edit",
    "lot_list",
    "lot_new",
    "lot_preview",
    "menu",
    "product_create",
    "product_toggle",
    "report",
    "roast_delete",
    "roast_detail",
    "roast_edit",
    "roast_list",
    "roast_new",
    "roast_preview",
    "sale_delete",
    "sale_detail",
    "sale_edit",
    "sale_list",
    "sale_new",
    "sale_preview",
]
