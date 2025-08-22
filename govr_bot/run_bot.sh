#!/bin/bash
set -Eeuo pipefail

# Всегда работаем из директории, где лежит скрипт
cd "$(dirname "$0")"

echo "[run_bot] Рабочая папка: $(pwd)"

# Включаем логирование всего вывода в файл
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
ln -s -f "$(basename "$LOG_FILE")" "$LOG_DIR/latest.log" || true
echo "[run_bot] Логи: $(pwd)/$LOG_FILE (symlink: $(pwd)/$LOG_DIR/latest.log)"

source venv/bin/activate || { echo "[run_bot] Нет venv. Создайте: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"; exit 1; }
echo "[run_bot] Python: $(python --version)"

# Проверяем наличие .env (для BOT_TOKEN)
if [ ! -f ".env" ]; then
    echo "[run_bot] Внимание: файл .env не найден. Создайте .env со строкой:\nBOT_TOKEN=..."
    echo "[run_bot] Полный лог: $(pwd)/$LOG_FILE"
    exit 1
fi

# 4.1) Проверяем, что BOT_TOKEN действительно задан (не пустой и не заглушка)
BOT_TOKEN_VAL="$(grep -E '^BOT_TOKEN=' .env | sed 's/^BOT_TOKEN=//; s/^\"//; s/\"$//')"
if [ -z "${BOT_TOKEN_VAL:-}" ] || [[ "${BOT_TOKEN_VAL}" == "ВАШ_ТОКЕН_ТЕЛЕГРАМ" ]] || [[ "${BOT_TOKEN_VAL}" == "<PUT_YOUR_TOKEN_HERE>" ]]; then
    echo "[run_bot] Ошибка: переменная BOT_TOKEN в .env не задана или содержит заглушку."
    echo "Откройте файл $(pwd)/.env и укажите реальный токен, который вы получили у BotFather."
    echo "Пример строки: BOT_TOKEN=123456789:AA..."
    echo "[run_bot] Полный лог: $(pwd)/$LOG_FILE"
    exit 1
fi

# Запускаем бота
echo "[run_bot] Запускаю бота..."
if python3 -m bot.main "$@"; then
    echo "[run_bot] Бот завершился корректно. Лог: $(pwd)/$LOG_FILE"
    # Пауза для сценария «двойной клик в файловом менеджере». Отключить: RUN_BOT_NO_PAUSE=1 ./run_bot.sh
    if [ -z "${RUN_BOT_NO_PAUSE:-}" ]; then echo "Нажмите Enter, чтобы закрыть окно..."; read -r; fi
    exit 0
else
    status=$?
    echo "[run_bot] Бот завершился с ошибкой (код $status). Полный лог: $(pwd)/$LOG_FILE"
    if [ -z "${RUN_BOT_NO_PAUSE:-}" ]; then echo "Нажмите Enter, чтобы закрыть окно..."; read -r; fi
    exit "$status"
fi
