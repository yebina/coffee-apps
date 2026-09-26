# コーヒー豆 在庫管理アプリ

生豆の仕入れ・焙煎・販売を記録し、在庫と原価・粗利を管理する Web アプリ。

- 仕様書：[docs/spec.md](docs/spec.md)
- アーキテクチャ：[docs/architecture.md](docs/architecture.md)
- 画面のデモ：[docs/demo.html](docs/demo.html)

## 開発の始め方

[uv](https://docs.astral.sh/uv/) と Docker を使う。

```sh
cp .env.example .env
docker compose up -d          # PostgreSQL を起動
uv sync                       # Python とライブラリを入れる
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

## テストとチェック

```sh
uv run pytest
uv run ruff check .
uv run ruff format .
```

## コードの構成

| ファイル | 内容 |
|---|---|
| `inventory/models.py` | テーブル。残量は保存せず、`with_stock()` で計算して付ける |
| `inventory/calc.py` | 計算ルール（仕様書「5」）。表示するときだけ四捨五入する |
| `inventory/services.py` | 在庫を動かす処理（焙煎・販売・在庫調整）。行をロックしてから残量を確かめる |
| `inventory/admin.py` | 管理画面。問屋と選択肢の編集に使う |

画面の処理から在庫を直接書き換えず、必ず `services.py` を通す。
