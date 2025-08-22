#!/bin/bash
set -Eeuo pipefail

# Рабочая директория = папка скрипта
cd "$(dirname "$0")"

echo "[run_parent_bot] Рабочая папка: $(pwd)"

# Логи
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
ln -s -f "$(basename "$LOG_FILE")" "$LOG_DIR/latest.log" || true
echo "[run_parent_bot] Логи: $(pwd)/$LOG_FILE (symlink: $(pwd)/$LOG_DIR/latest.log)"

# venv (только активируем; если нет — сообщим)
source venv/bin/activate || { echo "[run_parent_bot] Нет venv. Создайте: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"; exit 1; }
echo "[run_parent_bot] Python: $(python --version)"

# .env
if [ ! -f .env ]; then
  echo "[run_parent_bot] Внимание: нет .env. Создайте его со строками:\nBOT_TOKEN=...\nOPENAI_API_KEY=...\n(опц.) USERS_DB=абсолютный_путь_к_shared/users.db"
  exit 1
fi

# Проверим токен
PARENT_BOT_TOKEN=$(grep -E '^BOT_TOKEN=' .env | sed 's/^BOT_TOKEN=//; s/^"//; s/"$//')
if [ -z "${PARENT_BOT_TOKEN:-}" ]; then
  echo "[run_parent_bot] BOT_TOKEN пуст. Укажите реальный токен."; exit 1
fi

echo "[run_parent_bot] Запускаю..."
if python3 -m bot.main "$@"; then
  echo "[run_parent_bot] Завершено"; exit 0
else
  code=$?; echo "[run_parent_bot] Ошибка $code"; exit $code
fi


