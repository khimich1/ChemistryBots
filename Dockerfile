FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Кешируем установку зависимостей
COPY govr_bot/requirements.txt /app/govr_bot/requirements.txt
COPY prepod_bot/requirements.txt /app/prepod_bot/requirements.txt
COPY parent_bot/requirements.txt /app/parent_bot/requirements.txt
COPY admin_bot/requirements.txt /app/admin_bot/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
    -r /app/govr_bot/requirements.txt \
    -r /app/prepod_bot/requirements.txt \
    -r /app/parent_bot/requirements.txt \
    -r /app/admin_bot/requirements.txt

# Теперь весь код
COPY . /app


