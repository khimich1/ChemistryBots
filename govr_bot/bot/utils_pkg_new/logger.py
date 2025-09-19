import logging
import sys
from pathlib import Path
from datetime import datetime
import json
from typing import Any, Dict

def setup_logging():
    """Настройка структурированного логирования для бота"""
    
    # Создаем папку для логов
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Настройка формата для обычных логов
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Структурированный форматтер для JSON логов
    class JSONFormatter(logging.Formatter):
        def format(self, record):
            log_entry = {
                'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
                'module': record.module,
                'function': record.funcName,
                'line': record.lineno
            }
            
            # Добавляем дополнительные поля если есть
            if hasattr(record, 'user_id'):
                log_entry['user_id'] = record.user_id
            if hasattr(record, 'action'):
                log_entry['action'] = record.action
            if hasattr(record, 'details'):
                log_entry['details'] = record.details
                
            return json.dumps(log_entry, ensure_ascii=False)
    
    # Файловый хендлер для всех логов
    file_handler = logging.FileHandler(log_dir / "bot.log", encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Файловый хендлер для ошибок (JSON формат)
    error_handler = logging.FileHandler(log_dir / "errors.log", encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())
    
    # Консольный хендлер
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    
    # Настройка корневого логгера
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Очищаем существующие хендлеры
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Добавляем новые хендлеры
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    
    # Отключаем логи от сторонних библиотек
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Создаем логгер для бота
    bot_logger = logging.getLogger("chemistry_bot")
    bot_logger.info("Логирование настроено")

def log_user_action(user_id: int, action: str, details: Dict[str, Any] = None):
    """Логирует действия пользователя"""
    logger = logging.getLogger("chemistry_bot.user_actions")
    
    # Создаем запись с дополнительными полями
    record = logger.makeRecord(
        "chemistry_bot.user_actions", 
        logging.INFO, 
        "", 
        0, 
        f"User action: {action}", 
        (), 
        None
    )
    record.user_id = user_id
    record.action = action
    record.details = details or {}
    
    logger.handle(record)

def log_error(error: Exception, context: str = "", user_id: int = None):
    """Логирует ошибки с контекстом"""
    import sys
    logger = logging.getLogger("chemistry_bot.errors")
    
    # Получаем правильный exc_info
    exc_info = sys.exc_info() if error else None
    
    record = logger.makeRecord(
        "chemistry_bot.errors",
        logging.ERROR,
        "",
        0,
        f"Error in {context}: {str(error)}",
        (),
        exc_info
    )
    if user_id:
        record.user_id = user_id
    record.details = {"context": context, "error_type": type(error).__name__}
    
    logger.handle(record)

def log_database_operation(operation: str, success: bool, details: Dict[str, Any] = None):
    """Логирует операции с базой данных"""
    logger = logging.getLogger("chemistry_bot.database")
    level = logging.INFO if success else logging.ERROR
    
    record = logger.makeRecord(
        "chemistry_bot.database",
        level,
        "",
        0,
        f"Database operation: {operation} - {'SUCCESS' if success else 'FAILED'}",
        (),
        None
    )
    record.details = details or {}
    
    logger.handle(record)
