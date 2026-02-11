#!/bin/bash
set -Eeuo pipefail

# Быстрый запуск parent_bot для разработки (без полной инициализации)
cd "$(dirname "$0")"

echo "⚡ [run_parent_bot] Быстрый запуск parent_bot..."
echo "📁 [run_parent_bot] Рабочая папка: $(pwd)"

# Логирование
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
ln -s -f "$(basename "$LOG_FILE")" "$LOG_DIR/latest.log" || true

# Функции для красивого вывода
show_progress() { echo "⏳ [run_parent_bot] $1"; }
show_success() { echo "✅ [run_parent_bot] $1"; }
show_error() { echo "❌ [run_parent_bot] $1"; }

# Быстрые проверки
show_progress "Быстрая проверка окружения..."
source venv/bin/activate || { show_error "venv не найден!"; exit 1; }

if [ ! -f ".env" ]; then
    show_error "Файл .env не найден!"
    exit 1
fi

# Проверяем токен быстро
BOT_TOKEN_VAL="$(grep -E '^BOT_TOKEN=' .env | sed 's/^BOT_TOKEN=//; s/^\"//; s/\"$//')"
if [ -z "${BOT_TOKEN_VAL:-}" ] || [[ "${BOT_TOKEN_VAL}" == "ВАШ_ТОКЕН_ТЕЛЕГРАМ" ]]; then
    show_error "BOT_TOKEN не задан!"
    exit 1
fi

show_success "Окружение готово"

# Запускаем с переменной окружения для пропуска инициализации БД
show_progress "Запускаю parent_bot в быстром режиме..."
export SKIP_DB_INIT=1
START_TIME=$(date +%s)

if python3 -m bot.main "$@"; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    show_success "Parent_bot завершился за ${DURATION} секунд"
    if [ -z "${RUN_BOT_NO_PAUSE:-}" ]; then echo "Нажмите Enter..."; read -r; fi
    exit 0
else
    status=$?
    show_error "Ошибка (код $status)"
    if [ -z "${RUN_BOT_NO_PAUSE:-}" ]; then echo "Нажмите Enter..."; read -r; fi
    exit "$status"
fi


