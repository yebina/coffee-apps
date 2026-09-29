# 豆帳：Fly.io で動かすイメージ（architecture.md「7」）
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 依存ライブラリ（uv.lock のとおりに入れる。開発用は入れない）
RUN pip install --no-cache-dir uv==0.8.17
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# アプリ本体
COPY config ./config
COPY inventory ./inventory
COPY static ./static
COPY manage.py ./

# CSS などをまとめる（WhiteNoise で配信する）。ビルドのときだけの仮の値を使う
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=postgres://build@localhost/build \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000
# メモリ 512MB のマシン1台なので、ワーカーは 2つにする
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "30", \
     "--access-logfile", "-"]
