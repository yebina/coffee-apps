# 豆帳 公開と運用の手順

- 対象：[アーキテクチャ提案](architecture.md) v0.3 の構成（Fly.io 東京 ＋ Supabase 東京 ＋ Cloudflare R2）
- 状態：手順は書いたが、本番の公開はまだしていない。バックアップから戻す手順は、自分の PC と同じ形の PostgreSQL で試した（「6」）

## 1. 全体の流れ

1. Supabase のプロジェクトを作る（「2」）
2. Fly.io にアプリを作り、秘密の値を入れて公開する（「3」）
3. 自分のログイン用アカウントを作る（「3.4」）
4. GitHub Actions から自動で公開できるようにする（「4」）
5. 毎晩のバックアップを設定する（「5」）
6. 使い始める前に、バックアップから戻す練習をする（「6」）

コマンドは自分の PC で実行する。`flyctl`（Fly.io のコマンド）は <https://fly.io/docs/flyctl/install/> の手順で入れる。

## 2. Supabase（データベース）

1. Supabase で新しいプロジェクトを作る
   - Region：**Northeast Asia (Tokyo)**
   - Database Password：長いランダムな文字列にして、パスワード管理ソフトに保存する
   - 開発中は Free、本番で使い始めるときに Pro にする（Free は 7日間ほとんど使わないと一時停止し、自動のバックアップもない）
2. **SSL を必須にする**：Database Settings → SSL Configuration → Enforce SSL on incoming connections をオン（DB が短い時間だけ再起動するので、使い始める前に行う）
3. **Data API をオフにする**：Project Settings → Data API → Enable Data API をオフ（このアプリは使わない。オンのままだと、Django のテーブルがプロジェクトの URL から読み書きできる状態になりうる）
4. 接続文字列を 2つ控える（画面上部の Connect から）
   - **Direct connection**（Fly.io のアプリ用。IPv6）
     `postgresql://postgres:［パスワード］@db.［プロジェクトID］.supabase.co:5432/postgres`
   - **Session pooler**（毎晩のバックアップ用。GitHub Actions は IPv6 で接続できないため）
     `postgresql://postgres.［プロジェクトID］:［パスワード］@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres`

アプリは本番（`DJANGO_DEBUG` なし）では、接続に SSL を必ず使う（`sslmode=require`）。

## 3. Fly.io（公開先）

### 3.1 アプリを作る

```sh
fly auth login
fly launch --no-deploy --copy-config --name ［アプリ名］ --region nrt
```

- `［アプリ名］` は Fly.io 全体で重ならない名前にする（例：`mamecho-［自分の名前］`）。URL は `https://［アプリ名］.fly.dev` になる
- `fly.toml` の `app`、`DJANGO_ALLOWED_HOSTS`、`DJANGO_CSRF_TRUSTED_ORIGINS` を、作ったアプリ名に合わせて書き換えてコミットする
- 独自ドメインを使うときは `fly certs add ［ドメイン］` のあと、`DJANGO_ALLOWED_HOSTS` と `DJANGO_CSRF_TRUSTED_ORIGINS` にカンマ区切りで足す

### 3.2 秘密の値を入れる

```sh
fly secrets set \
  DJANGO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  DATABASE_URL='［Supabase の Direct connection の文字列］' \
  DJANGO_ADMIN_PATH='［推測されにくい文字列］/'
```

| 名前 | 内容 |
|---|---|
| `DJANGO_SECRET_KEY` | Django の秘密鍵。ランダムな文字列（上のコマンドで作る） |
| `DATABASE_URL` | Supabase の Direct connection の接続文字列 |
| `DJANGO_ADMIN_PATH` | 管理画面の URL。例：`kanri-7f3k9q/`（最後に `/` を付ける）。設定しないと `admin/` になる |

秘密の値はリポジトリに置かない。変えるときも `fly secrets set` を使う（マシンが入れ替わる）。

### 3.3 公開する

```sh
fly deploy
```

- 公開のたびに、新しいマシンに切り替わる前に DB の構造変更（`migrate`）が実行される（`fly.toml` の `release_command`）
- `https://［アプリ名］.fly.dev/healthz` が `ok` を返せば、アプリは動いている

### 3.4 ログイン用のアカウントを作る

```sh
fly ssh console -C "python manage.py createsuperuser"
```

新規登録の画面はないので、このアカウントだけを使う。ログインに 5回続けて失敗すると、同じユーザー名・同じ回線からは 1時間ログインできなくなる（別の回線、たとえばスマホの通信からならログインできる）。すぐに解除したいときは：

```sh
fly ssh console -C "python manage.py axes_reset"
```

## 4. GitHub Actions から自動で公開する

`main` ブランチに入ると、テストが通ったあとで Fly.io に公開する（`.github/workflows/ci.yml` の `deploy`）。

1. 公開用のトークンを作る：`fly tokens create deploy -x 999999h`
2. GitHub のリポジトリ → Settings → Secrets and variables → Actions で設定する

| 種類 | 名前 | 値 |
|---|---|---|
| Secret | `FLY_API_TOKEN` | 1 で作ったトークン |
| Variable | `FLY_DEPLOY` | `true` |

`FLY_DEPLOY` が `true` でないあいだは、公開の手順は動かない（テストだけ動く）。

## 5. 毎晩のバックアップ（Cloudflare R2）

毎日 3:00（日本時間）に `pg_dump` を取り、R2 に保存する。30日より古いものは消す（`.github/workflows/backup.yml`）。Supabase Pro の自動バックアップ（直近 7日）とは別に、アプリとは別の会社に保管するためのもの（仕様書 8）。

1. Cloudflare で R2 を使えるようにし、バケットを作る（例：`mamecho-backup`。公開アクセスはオフのまま）
2. R2 → Manage API tokens で、**このバケットだけ**に Object Read & Write の権限を持つトークンを作る。Access Key ID と Secret Access Key、エンドポイント（`https://［アカウントID］.r2.cloudflarestorage.com`）を控える
3. GitHub のリポジトリに設定する

| 種類 | 名前 | 値 |
|---|---|---|
| Secret | `BACKUP_DATABASE_URL` | Supabase の Session pooler の接続文字列 |
| Secret | `R2_ACCESS_KEY_ID` | R2 のトークンの Access Key ID |
| Secret | `R2_SECRET_ACCESS_KEY` | R2 のトークンの Secret Access Key |
| Secret | `R2_ENDPOINT` | `https://［アカウントID］.r2.cloudflarestorage.com` |
| Variable | `R2_BUCKET` | バケット名 |
| Variable | `BACKUP_ENABLED` | `true` |

4. Actions → Backup → Run workflow で 1回動かし、R2 のバケットの `db/` に `2026-09-30_0300.dump` のようなファイルができることを確かめる

バックアップが失敗すると、GitHub から失敗のお知らせのメールが届く。

## 6. バックアップから戻す

### 6.1 戻す練習（最初の公開の前と、3か月に1回）

本番の DB は触らずに、自分の PC の PostgreSQL に戻して、中身が本番と同じか確かめる。

1. R2 から、いちばん新しいダンプをダウンロードする（Cloudflare の画面から、または `aws s3 cp`）
2. 自分の PC で、空の DB を用意して戻す

```sh
docker compose up -d
docker compose exec db psql -U coffee -c 'CREATE DATABASE coffee_restore;'
docker compose exec -T db pg_restore --no-owner --no-privileges -U coffee -d coffee_restore < ［ダウンロードしたファイル］.dump
```

3. 戻した DB と本番で、件数と在庫の合計を比べる（ダンプを取ったあとに記録したぶんだけ、本番のほうが多くてよい）

```sh
DATABASE_URL=postgres://coffee:coffee@localhost:5432/coffee_restore uv run python manage.py inventory_summary
fly ssh console -C "python manage.py inventory_summary"
```

4. 戻した DB でアプリを起動し、ログインして画面が見られることを確かめる

```sh
DATABASE_URL=postgres://coffee:coffee@localhost:5432/coffee_restore uv run python manage.py runserver
```

5. 下の「練習の記録」に結果を書き足す

### 6.2 本当に戻すとき

1. Supabase で新しいプロジェクトを作り、「2」の設定をする
2. ダンプを戻す（`［新しい DB の接続文字列］` は Direct connection か Session pooler のもの）

```sh
docker run --rm -i postgres:17 pg_restore --no-owner --no-privileges -d '［新しい DB の接続文字列］' < ［ダンプ］.dump
```

3. アプリの接続先を変える：`fly secrets set DATABASE_URL='［新しい DB の Direct connection］'`
4. `BACKUP_DATABASE_URL` も新しい DB の Session pooler に変える

Supabase Pro の自動バックアップ（直近 7日）から戻すときは、Supabase の画面（Database → Backups）から戻す。

### 練習の記録

| 日付 | 使ったダンプ | 結果 | メモ |
|---|---|---|---|
| 2026-09-29 | 開発用の DB（ローカルの PostgreSQL 16）から取ったもの | 戻せた。`inventory_summary` の結果が元の DB と同じ | 本番の公開前の手順の確認。本番のダンプで、もう一度行う |

## 7. 日々の運用

| したいこと | コマンド・場所 |
|---|---|
| ログを見る | `fly logs` |
| マシンの状態を見る | `fly status` |
| 前の版に戻す | `fly releases` で版を確かめ、`fly deploy --image ［前の版のイメージ］` |
| 管理画面を開く | `https://［アプリ名］.fly.dev/［DJANGO_ADMIN_PATH］` |
| ログインの制限を解除する | `fly ssh console -C "python manage.py axes_reset"` |
| DB の使用量を見る | Supabase の画面（Reports） |
| 費用を見る | Fly.io の Billing、Supabase の Usage |

- Django の版を上げる：Django 6.1 のサポートは 2027年12月まで。それまでに次の版に上げる（architecture.md「3」）
- Supabase の PostgreSQL のメジャー版を上げるときは、上げている間はアプリが使えない。毎晩のバックアップの `postgres:17` も、同じ版かそれより新しい版に合わせる

## 8. 設定値の一覧

アプリが読む環境変数。自分の PC では `.env` に書く（`.env.example` を参照）。

| 名前 | 本番 | 説明 |
|---|---|---|
| `DJANGO_SECRET_KEY` | 必須（secret） | Django の秘密鍵 |
| `DATABASE_URL` | 必須（secret） | DB の接続文字列 |
| `DJANGO_ADMIN_PATH` | 推奨（secret） | 管理画面の URL（最後に `/`） |
| `DJANGO_ALLOWED_HOSTS` | 必須（fly.toml） | カンマ区切りのホスト名 |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | 必須（fly.toml） | カンマ区切りの `https://〜` |
| `DJANGO_DEBUG` | 設定しない | 自分の PC だけ `true` |
| `DATABASE_SSL_REQUIRE` | 設定しない | DB の接続に SSL を使うか。初期値は `DJANGO_DEBUG` でないとき `true` |
| `DJANGO_SECURE_SSL_REDIRECT` | 設定しない | HTTP を HTTPS に転送するか。初期値は `true` |
