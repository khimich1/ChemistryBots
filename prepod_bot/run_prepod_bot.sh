#!/bin/bash
set -Eeuo pipefail

# Всегда работаем из директории, где лежит скрипт
cd "$(dirname "$0")"

echo "🚀 [run_prepod_bot] Запуск prepod бота..."
echo "📁 [run_prepod_bot] Рабочая папка: $(pwd)"

# Включаем логирование всего вывода в файл
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
ln -s -f "$(basename "$LOG_FILE")" "$LOG_DIR/latest.log" || true
echo "📝 [run_prepod_bot] Логи: $(pwd)/$LOG_FILE (symlink: $(pwd)/$LOG_DIR/latest.log)"

# Функция для показа прогресса
show_progress() {
    local message="$1"
    echo "⏳ [run_prepod_bot] $message"
}

# Функция для показа успеха
show_success() {
    local message="$1"
    echo "✅ [run_prepod_bot] $message"
}

# Функция для показа ошибки
show_error() {
    local message="$1"
    echo "❌ [run_prepod_bot] $message"
}

# Проверяем виртуальное окружение
show_progress "Проверяю виртуальное окружение..."
if [ ! -d "venv" ]; then
    show_error "Виртуальное окружение не найдено!"
    echo "Создайте его командой:"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

source venv/bin/activate || { 
    show_error "Не удалось активировать виртуальное окружение!"
    exit 1
}
show_success "Виртуальное окружение активировано"
echo "🐍 [run_prepod_bot] Python: $(python --version)"

# Проверяем наличие .env
show_progress "Проверяю конфигурацию..."
if [ ! -f ".env" ]; then
    show_error "Файл .env не найден!"
    echo "Создаю шаблон .env..."
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
    show_error "Файл .env создан, но нужно указать BOT_TOKEN!"
    echo "Откройте файл $(pwd)/.env и укажите реальный токен от BotFather"
    echo "Пример: BOT_TOKEN=123456789:AA..."
    echo "📝 [run_prepod_bot] Полный лог: $(pwd)/$LOG_FILE"
    exit 1
fi

# Проверяем BOT_TOKEN
BOT_TOKEN_VAL="$(grep -E '^BOT_TOKEN=' .env | sed 's/^BOT_TOKEN=//; s/^\"//; s/\"$//')"
if [ -z "${BOT_TOKEN_VAL:-}" ] || [[ "${BOT_TOKEN_VAL}" == "PUT_YOUR_TOKEN_HERE" ]] || [[ "${BOT_TOKEN_VAL}" == "ВАШ_ТОКЕН_ТЕЛЕГРАМ" ]]; then
    show_error "BOT_TOKEN не задан или содержит заглушку!"
    echo "Откройте файл $(pwd)/.env и укажите реальный токен от BotFather"
    echo "Пример: BOT_TOKEN=123456789:AA..."
    echo "📝 [run_prepod_bot] Полный лог: $(pwd)/$LOG_FILE"
    exit 1
fi
show_success "Конфигурация проверена"

# Проверяем зависимости
show_progress "Проверяю зависимости..."
if ! python3 -c "import aiogram" 2>/dev/null; then
    show_error "aiogram не установлен!"
    echo "Установите зависимости: pip install -r requirements.txt"
    exit 1
fi
show_success "Зависимости проверены"

# Останавливаем предыдущие запуски
show_progress "Останавливаю предыдущие запуски бота..."
pkill -f 'prepod_bot/main.py' >/dev/null 2>&1 || true

# Удаляем вебхук на всякий случай
if command -v curl >/dev/null 2>&1; then
    show_progress "Удаляю Telegram webhook..."
    curl -s "https://api.telegram.org/bot${BOT_TOKEN_VAL}/deleteWebhook" >/dev/null || true
fi

# Убеждаемся, что файлы БД существуют в shared
SHARED_DIR="/home/username/Рабочий стол/my py/ChemistryBots/shared"
mkdir -p "$SHARED_DIR"
touch "$SHARED_DIR/test_answers.db" "$SHARED_DIR/tests1.db"
show_success "Базы данных проверены в: $SHARED_DIR"

# Показываем прогресс загрузки
show_progress "Загружаю бота (это может занять 10-20 секунд)..."
echo "💡 [run_prepod_bot] Подсказка: первый запуск всегда медленнее из-за инициализации БД"

# Запускаем бота с таймером
START_TIME=$(date +%s)
if python3 main.py "$@"; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    show_success "Бот завершился корректно за ${DURATION} секунд"
    echo "📝 [run_prepod_bot] Лог: $(pwd)/$LOG_FILE"
    # Пауза для сценария «двойной клик в файловом менеджере». Отключить: RUN_BOT_NO_PAUSE=1 ./run_prepod_bot.sh
    if [ -z "${RUN_BOT_NO_PAUSE:-}" ]; then echo "Нажмите Enter, чтобы закрыть окно..."; read -r; fi
    exit 0
else
    status=$?
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    show_error "Бот завершился с ошибкой (код $status) за ${DURATION} секунд"
    echo "📝 [run_prepod_bot] Полный лог: $(pwd)/$LOG_FILE"
    if [ -z "${RUN_BOT_NO_PAUSE:-}" ]; then echo "Нажмите Enter, чтобы закрыть окно..."; read -r; fi
    exit "$status"
fi


