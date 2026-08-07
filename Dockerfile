# Tokyo Metro Alert (TMA) 公開用イメージ
FROM python:3.13-slim

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py db.py lines.py monitor.py timeutil.py tracking.py ./
COPY data ./data
COPY static ./static
COPY templates ./templates

# 実行ユーザーは管理者権限なし。DBは永続ディスク(/data)に置く
RUN useradd --create-home appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

ENV DATA_DIR=/data \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# 監視状態はプロセス内で持つため worker は必ず 1(並行処理は threads で行う)
CMD gunicorn --workers 1 --threads 8 --timeout 120 \
    --bind 0.0.0.0:${PORT:-8000} app:app
