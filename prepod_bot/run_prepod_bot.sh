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
# Рекомендуется использовать отдельные БД для ЕГЭ и ОГЭ
TESTS_DB_EGE="/home/username/Рабочий стол/my py/ChemistryBots/shared/test_ege.db"
TESTS_DB_OGE="/home/username/Рабочий стол/my py/ChemistryBots/shared/test_oge.db"

# Путь к базе пользователей, создаваемой admin_bot (таблица teacher)
USERS_DB="/home/username/Рабочий стол/my py/ChemistryBots/shared/users.db"

# Подсказка-ссылка для deep-link (используется в статистике рекламы)
# Пример: https://t.me/ИмяБота?start=ads1
DEEPLINK_HINT="https://t.me/ИмяБота?start=ads1"

# Необязательно: окно «онлайн» в минутах
ONLINE_WINDOW_MINUTES=10

# Ресурсы PDF/шрифтов
FONTS_DIR="/home/username/Рабочий стол/my py/ChemistryBots/shared/Fonts"
FONT_REGULAR="$FONTS_DIR/LiberationSerif-Regular.ttf"
FONT_BOLD="$FONTS_DIR/LiberationSerif-Bold.ttf"
PDF_BASE_IMAGE="$FONTS_DIR/PDF_base.png"
EOF
  echo "[run] .env template created at $SCRIPT_DIR/.env"
fi

# Проверим, что BOT_TOKEN задан и не равен плейсхолдеру
if ! grep -qE '^BOT_TOKEN=[^#[:space:]]' .env || grep -q 'BOT_TOKEN=PUT_YOUR_TOKEN_HERE' .env; then
  echo "[run] Please set BOT_TOKEN in $SCRIPT_DIR/.env (current is empty or placeholder)."
  echo "[run] Edit file and set your token from @BotFather, then re-run this script."
  exit 1
fi

# Остановим предыдущие запуски, чтобы избежать TelegramConflictError
echo "[run] Stopping previous bot instances (if any)..."
pkill -f 'prepod_bot/main.py' >/dev/null 2>&1 || true

# Удалим вебхук на всякий случай (если когда-то включали)
if command -v curl >/dev/null 2>&1; then
  BOT_TOKEN_VAL=$(grep '^BOT_TOKEN=' .env | head -1 | cut -d= -f2- | sed "s/^['\"]//; s/['\"]$//")
  if [ -n "$BOT_TOKEN_VAL" ] && [ "$BOT_TOKEN_VAL" != "PUT_YOUR_TOKEN_HERE" ]; then
    echo "[run] Deleting Telegram webhook..."
    curl -s "https://api.telegram.org/bot${BOT_TOKEN_VAL}/deleteWebhook" >/dev/null || true
  fi
fi

# Убедимся, что файлы БД существуют в shared (создадим пустые, если нет)
# Используем относительный путь от текущей директории
SHARED_DIR="$(dirname "$SCRIPT_DIR")/shared"
mkdir -p "$SHARED_DIR"
touch "$SHARED_DIR/test_answers.db" "$SHARED_DIR/tests1.db"
echo "[run] DB files ensured in: $SHARED_DIR"

# Запускаем бота с паузой после завершения
echo "[run] Starting bot..."
set +e
python main.py
status=$?
set -e
echo
echo "[run] Bot finished with exit code: $status"
if [ -z "${RUN_BOT_NO_PAUSE:-}" ]; then echo "Press Enter to close..."; read -r; fi
exit "$status"


