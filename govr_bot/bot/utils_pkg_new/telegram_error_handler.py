#!/usr/bin/env python3
"""
Улучшенный обработчик ошибок Telegram API
Специально для решения проблем с "message is not modified" и сетевыми ошибками
"""

import asyncio
import logging
from typing import Optional, Any, Callable, TypeVar
from functools import wraps
from aiogram.exceptions import (
    TelegramAPIError, TelegramBadRequest, TelegramForbiddenError,
    TelegramNetworkError, TelegramRetryAfter, TelegramMigrateToChat
)
from bot.utils_pkg_new.logger import log_error

T = TypeVar('T')

def handle_telegram_errors(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    log_errors: bool = True,
    user_id: Optional[int] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Декоратор для обработки всех типов ошибок Telegram API с повторными попытками.
    
    Args:
        max_retries: Максимальное количество повторных попыток
        retry_delay: Задержка между попытками в секундах
        log_errors: Логировать ли ошибки
        user_id: ID пользователя для логирования
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Optional[T]:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except TelegramBadRequest as e:
                    error_message = str(e).lower()
                    
                    # Обработка "message is not modified"
                    if "message is not modified" in error_message:
                        if log_errors:
                            log_error(e, f"Message not modified (ignored) in {func.__name__}", user_id=user_id)
                        return None  # Игнорируем эту ошибку
                    
                    # Обработка других ошибок BadRequest
                    elif "message to edit not found" in error_message:
                        if log_errors:
                            log_error(e, f"Message to edit not found in {func.__name__}", user_id=user_id)
                        return None
                    
                    elif "message is not editable" in error_message:
                        if log_errors:
                            log_error(e, f"Message is not editable in {func.__name__}", user_id=user_id)
                        return None
                    
                    else:
                        if log_errors:
                            log_error(e, f"Bad request in {func.__name__} (attempt {attempt + 1})", user_id=user_id)
                        last_exception = e
                        
                except TelegramRetryAfter as e:
                    # Telegram просит подождать
                    retry_after = e.retry_after
                    if log_errors:
                        log_error(e, f"Rate limit hit in {func.__name__}, waiting {retry_after}s", user_id=user_id)
                    
                    if attempt < max_retries:
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        last_exception = e
                        
                except TelegramNetworkError as e:
                    # Сетевые ошибки - пробуем повторить
                    if log_errors:
                        log_error(e, f"Network error in {func.__name__} (attempt {attempt + 1})", user_id=user_id)
                    
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay * (attempt + 1))  # Увеличиваем задержку
                        continue
                    else:
                        last_exception = e
                        
                except TelegramForbiddenError as e:
                    # Пользователь заблокировал бота
                    if log_errors:
                        log_error(e, f"User blocked bot in {func.__name__}", user_id=user_id)
                    return None
                    
                except TelegramMigrateToChat as e:
                    # Чат был перенесен
                    if log_errors:
                        log_error(e, f"Chat migrated in {func.__name__}", user_id=user_id)
                    return None
                    
                except TelegramAPIError as e:
                    # Другие ошибки API
                    if log_errors:
                        log_error(e, f"Telegram API error in {func.__name__} (attempt {attempt + 1})", user_id=user_id)
                    
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        last_exception = e
                        
                except Exception as e:
                    # Неожиданные ошибки
                    if log_errors:
                        log_error(e, f"Unexpected error in {func.__name__} (attempt {attempt + 1})", user_id=user_id)
                    
                    if attempt < max_retries:
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        last_exception = e
            
            # Если все попытки исчерпаны
            if log_errors and last_exception:
                log_error(last_exception, f"All retries failed in {func.__name__}", user_id=user_id)
            
            return None
        
        return wrapper
    return decorator

def safe_edit_message(
    log_errors: bool = True,
    user_id: Optional[int] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Специальный декоратор для безопасного редактирования сообщений.
    Обрабатывает все возможные ошибки при редактировании.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                return await func(*args, **kwargs)
                
            except TelegramBadRequest as e:
                error_message = str(e).lower()
                
                # Игнорируем "message is not modified"
                if "message is not modified" in error_message:
                    if log_errors:
                        log_error(e, f"Message not modified (ignored) in {func.__name__}", user_id=user_id)
                    return None
                
                # Игнорируем "message to edit not found"
                elif "message to edit not found" in error_message:
                    if log_errors:
                        log_error(e, f"Message to edit not found (ignored) in {func.__name__}", user_id=user_id)
                    return None
                
                # Логируем другие ошибки
                else:
                    if log_errors:
                        log_error(e, f"Bad request in {func.__name__}", user_id=user_id)
                    return None
                    
            except Exception as e:
                if log_errors:
                    log_error(e, f"Error in {func.__name__}", user_id=user_id)
                return None
        
        return wrapper
    return decorator

def safe_send_message(
    log_errors: bool = True,
    user_id: Optional[int] = None
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Специальный декоратор для безопасной отправки сообщений.
    Обрабатывает сетевые ошибки и ограничения.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                return await func(*args, **kwargs)
                
            except TelegramForbiddenError as e:
                # Пользователь заблокировал бота
                if log_errors:
                    log_error(e, f"User blocked bot in {func.__name__}", user_id=user_id)
                return None
                
            except TelegramRetryAfter as e:
                # Превышен лимит запросов
                if log_errors:
                    log_error(e, f"Rate limit in {func.__name__}", user_id=user_id)
                return None
                
            except TelegramNetworkError as e:
                # Сетевые проблемы
                if log_errors:
                    log_error(e, f"Network error in {func.__name__}", user_id=user_id)
                return None
                
            except Exception as e:
                if log_errors:
                    log_error(e, f"Error in {func.__name__}", user_id=user_id)
                return None
        
        return wrapper
    return decorator

# Утилитарные функции для проверки типов ошибок
def is_message_not_modified_error(error: Exception) -> bool:
    """Проверяет, является ли ошибка 'message is not modified'"""
    return (
        isinstance(error, TelegramBadRequest) and 
        "message is not modified" in str(error).lower()
    )

def is_network_error(error: Exception) -> bool:
    """Проверяет, является ли ошибка сетевой"""
    return isinstance(error, TelegramNetworkError)

def is_rate_limit_error(error: Exception) -> bool:
    """Проверяет, является ли ошибка превышением лимита"""
    return isinstance(error, TelegramRetryAfter)

def is_user_blocked_error(error: Exception) -> bool:
    """Проверяет, заблокировал ли пользователь бота"""
    return isinstance(error, TelegramForbiddenError)

# Примеры использования:
"""
@handle_telegram_errors(max_retries=3, retry_delay=1.0)
async def send_message_with_retry(chat_id: int, text: str):
    return await bot.send_message(chat_id, text)

@safe_edit_message()
async def edit_message_safely(chat_id: int, message_id: int, text: str):
    return await bot.edit_message_text(text, chat_id, message_id)

@safe_send_message()
async def send_message_safely(chat_id: int, text: str):
    return await bot.send_message(chat_id, text)
"""
