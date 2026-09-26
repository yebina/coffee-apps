"""選択肢の初期値（仕様書 4.2・4.5・4.6）。あとから管理画面で変えられる。"""

from django.db import migrations

DEFAULTS = {
    "sales_channel": ["店頭", "ネットショップ", "イベント", "卸", "その他"],
    "process": ["ウォッシュド", "フリーウォッシュド", "ナチュラル", "ハニープロセス"],
    "rank": [
        "トップオブトップ",
        "トップスペシャルティ",
        "スペシャルティコーヒー",
        "プレミアムコーヒー",
        "コマーシャルコーヒー",
    ],
    "certification": [
        "有機JAS",
        "フェアトレード",
        "レインフォレスト・アライアンス",
        "カップ・オブ・エクセレンス",
    ],
    "adjustment_reason": ["試飲・自家用", "サンプル", "廃棄", "棚卸しの差", "その他"],
}


def seed(apps, schema_editor):
    ChoiceOption = apps.get_model("inventory", "ChoiceOption")
    for category, labels in DEFAULTS.items():
        for i, label in enumerate(labels):
            ChoiceOption.objects.get_or_create(
                category=category, label=label, defaults={"sort_order": (i + 1) * 10}
            )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
