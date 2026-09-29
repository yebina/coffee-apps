"""すべての画面で使う値（メニューのどこにいるか）。"""

SECTIONS = {
    "home": "home",
    "lot": "lots",
    "roast": "roasts",
    "coffee": "coffees",
    "product": "coffees",
    "sale": "sales",
    "adjust": "adjust",
    "report": "reports",
    "menu": "menu",
}

# スマホのタブで「その他」にまとめる画面
MENU_SECTIONS = {"coffees", "adjust", "reports", "menu"}


def nav(request):
    match = getattr(request, "resolver_match", None)
    name = match.url_name if match else ""
    prefix = (name or "").split("_", 1)[0]
    section = SECTIONS.get(prefix, "")
    return {"nav_section": section, "nav_in_menu": section in MENU_SECTIONS}
