import logging
import sqlite3
from typing import Callable, Any, TypeVar, Optional, Union
from functools import wraps
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from bot.utils_pkg_new.logger import log_error

T = TypeVar('T')

def safe_execute(
    error_message: str = "Произошла ошибка",
    log_error_flag: bool = True,
    default_return: Optional[T] = None,
    user_id: Optional[int] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Декоратор для безопасного выполнения функций с правильной обработкой ошибок.
    
    Args:
        error_message: Сообщение об ошибке для пользователя
        log_error_flag: Логировать ли ошибки
        default_return: Значение по умолчанию при ошибке
        user_id: ID пользователя для логирования
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                return func(*args, **kwargs)
            except (ValueError, TypeError) as e:
                # Ошибки данных - логируем как warning
                if log_error_flag:
                    log_error(e, f"Data error in {func.__name__}", user_id=user_id)
                return default_return
            except (sqlite3.OperationalError, sqlite3.Error) as e:
                # Ошибки БД - логируем как error
                if log_error_flag:
                    log_error(e, f"Database error in {func.__name__}", user_id=user_id)
                return default_return
            except Exception as e:
                # Неожиданные ошибки - логируем как error
                if log_error_flag:
                    log_error(e, f"Unexpected error in {func.__name__}", user_id=user_id)
                return default_return
        
        return wrapper
    return decorator

def safe_telegram_execute(
    fallback_message: str = "Произошла ошибка. Попробуйте позже.",
    log_error_flag: bool = True,
    user_id: Optional[int] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Декоратор для безопасного выполнения Telegram API операций.
    
    Args:
        fallback_message: Сообщение для пользователя при ошибке
        log_error_flag: Логировать ли ошибки
        user_id: ID пользователя для логирования
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                return await func(*args, **kwargs)
            except TelegramForbiddenError as e:
                # Пользователь заблокировал бота
                if log_error_flag:
                    log_error(e, f"User blocked bot in {func.__name__}", user_id=user_id)
                return None
            except TelegramBadRequest as e:
                # Неправильный запрос
                if log_error_flag:
                    log_error(e, f"Bad request in {func.__name__}", user_id=user_id)
                return None
            except TelegramAPIError as e:
                # Проблемы с Telegram API
                if log_error_flag:
                    log_error(e, f"Telegram API error in {func.__name__}", user_id=user_id)
                return None
            except Exception as e:
                # Неожиданные ошибки
                if log_error_flag:
                    log_error(e, f"Unexpected error in {func.__name__}", user_id=user_id)
                return None
        
        return wrapper
    return decorator

def safe_database_operation(
    operation_name: str,
    log_error_flag: bool = True,
    user_id: Optional[int] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Декоратор для безопасного выполнения операций с базой данных.
    
    Args:
        operation_name: Название операции для логирования
        log_error_flag: Логировать ли ошибки
        user_id: ID пользователя для логирования
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                result = func(*args, **kwargs)
                # Логируем успешную операцию
                if log_error_flag:
                    from bot.utils_pkg_new.logger import log_database_operation
                    log_database_operation(operation_name, True, {"user_id": user_id})
                return result
            except sqlite3.OperationalError as e:
                # Таблицы нет или проблемы с БД
                if log_error_flag:
                    log_error(e, f"Database operational error in {operation_name}", user_id=user_id)
                return None
            except sqlite3.Error as e:
                # Другие ошибки SQLite
                if log_error_flag:
                    log_error(e, f"SQLite error in {operation_name}", user_id=user_id)
                return None
            except Exception as e:
                # Неожиданные ошибки
                if log_error_flag:
                    log_error(e, f"Unexpected error in {operation_name}", user_id=user_id)
                return None
        
        return wrapper
    return decorator

def handle_user_input_safely(
    validation_func: Optional[Callable[[str], bool]] = None,
    error_message: str = "Некорректные данные. Попробуйте еще раз.",
    log_error_flag: bool = True,
    user_id: Optional[int] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Декоратор для безопасной обработки пользовательского ввода.
    
    Args:
        validation_func: Функция валидации ввода
        error_message: Сообщение об ошибке
        log_error_flag: Логировать ли ошибки
        user_id: ID пользователя для логирования
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                # Валидация ввода если предоставлена функция
                if validation_func and 'message' in kwargs:
                    message = kwargs['message']
                    if hasattr(message, 'text') and message.text:
                        if not validation_func(message.text):
                            if log_error_flag:
                                log_error(ValueError("Invalid user input"), f"Input validation failed in {func.__name__}", user_id=user_id)
                            return None
                
                return await func(*args, **kwargs)
            except UnicodeDecodeError as e:
                # Проблемы с кодировкой
                if log_error_flag:
                    log_error(e, f"Unicode error in {func.__name__}", user_id=user_id)
                return None
            except ValueError as e:
                # Проблемы с данными
                if log_error_flag:
                    log_error(e, f"Value error in {func.__name__}", user_id=user_id)
                return None
            except Exception as e:
                # Неожиданные ошибки
                if log_error_flag:
                    log_error(e, f"Unexpected error in {func.__name__}", user_id=user_id)
                return None
        
        return wrapper
    return decorator

# Примеры использования:
# @safe_execute(error_message="Не удалось получить статистику", default_return=(0, 0))
# def get_user_stats(user_id: int) -> tuple[int, int]:
#     # Ваш код здесь
#     pass

# @safe_telegram_execute(fallback_message="Не удалось отправить сообщение")
# async def send_message_to_user(user_id: int, text: str):
#     # Telegram API код здесь
#     pass

# @safe_database_operation("get_user_profile")
# def get_user_profile(user_id: int):
#     # Операции с БД здесь
#     pass
