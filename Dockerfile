# TOYOCHO ALERT Ver2 の入れ物（Render公開用）。
FROM python:3.13-slim

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ver2の本体に必要な部品だけを入れる（Ver1のFlask等は入れない）
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY toyocho ./toyocho
COPY web ./web

# 実行ユーザーは管理者権限なし。データは永続ディスク（/data）に置く
RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

ENV DATABASE_URL=sqlite:////data/toyocho.db \
    COOKIE_SECURE=true \
    PYTHONUTF8=1

EXPOSE 8100
# Renderは待ち受け口（PORT）を環境変数で渡してくる。未指定なら8100（手元での確認用）
CMD python -m uvicorn toyocho.api:app --host 0.0.0.0 --port ${PORT:-8100}
