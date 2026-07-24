FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY backend ./backend
RUN python -m pip install --upgrade pip \
    && python -m pip install .

COPY scripts ./scripts
COPY storage/natural_language ./storage/natural_language
COPY storage/strategies ./storage/strategies

EXPOSE 8000

CMD ["sh", "-c", "python scripts/init_db.py && exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
