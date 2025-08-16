#!/usr/bin/env bash
set -euo pipefail

# Определяем директорию скрипта и переходим в неё
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo "[run] Working dir: $SCRIPT_DIR"

# Находим доступный Python интерпретатор
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[run] Python не найден. Установите python3."
  exit 1
fi

create_venv() {
  echo "[run] Creating Python venv with: $PY -m venv venv"
  if ! $PY -m venv venv 2>/tmp/venv_err.log; then
    echo "[run] Не удалось создать venv. Подсказка для Ubuntu/Mint:"
    echo "      sudo apt update && sudo apt install -y python3-venv"
    echo "[run] Полный лог ошибки:"
    cat /tmp/venv_err.log
    exit 1
  fi
}

# Создаём/восстанавливаем venv, если файл активатора отсутствует
if [ ! -f "venv/bin/activate" ]; then
  echo "[run] venv/bin/activate не найден. Пересоздаю окружение..."
  rm -rf venv
  create_venv
fi

# Активируем venv
source "venv/bin/activate"
echo "[run] Python: $(python --version)"

# Обновляем pip и ставим зависимости
pip install --upgrade pip
pip install -r requirements.txt

# Создаём .env с шаблоном, если отсутствует
if [ ! -f ".env" ]; then
  echo "[run] Creating .env template..."
  cat > .env <<'EOF'
# Токен бота (обязательно)
BOT_TOKEN=PUT_YOUR_TOKEN_HERE

# Необязательно: ID админов через запятую
ADMIN_IDS=

# Пути к БД в общей папке shared (оставьте как есть, если базы лежат там)
DB_PATH="/home/username/Рабочий стол/my py/ChemistryBots/shared/test_answers.db"
TESTS_DB_PATH="/home/username/Рабочий стол/my py/ChemistryBots/shared/tests1.db"

# Необязательно: окно «онлайн» в минутах
ONLINE_WINDOW_MINUTES=10
EOF
  echo "[run] .env template created at $SCRIPT_DIR/.env"
fi

# Проверим, что BOT_TOKEN задан и не равен плейсхолдеру
if ! grep -qE '^BOT_TOKEN=[^#[:space:]]' .env || grep -q 'BOT_TOKEN=PUT_YOUR_TOKEN_HERE' .env; then
  echo "[run] Please set BOT_TOKEN in $SCRIPT_DIR/.env (current is empty or placeholder)."
  echo "[run] Edit file and set your token from @BotFather, then re-run this script."
  exit 1
fi

# Убедимся, что файлы БД существуют в shared (создадим пустые, если нет)
SHARED_DIR="/home/username/Рабочий стол/my py/ChemistryBots/shared"
mkdir -p "$SHARED_DIR"
touch "$SHARED_DIR/test_answers.db" "$SHARED_DIR/tests1.db"
echo "[run] DB files ensured in: $SHARED_DIR"

# Запускаем бота
echo "[run] Starting bot..."
exec python main.py


