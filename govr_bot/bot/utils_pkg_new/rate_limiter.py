#!/usr/bin/env python3
"""
Rate limiter для защиты от спама и управления нагрузкой.
"""

import asyncio
import time
from typing import Dict
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)

# Глобальные хранилища для rate limiting
_user_requests: Dict[int, deque] = defaultdict(lambda: deque())
_user_last_request: Dict[int, float] = {}

# Настройки rate limiting
MAX_REQUESTS_PER_MINUTE = 30  # Максимум запросов в минуту на пользователя
MAX_REQUESTS_PER_HOUR = 200   # Максимум запросов в час на пользователя
CLEANUP_INTERVAL = 300        # Интервал очистки в секундах (5 минут)

async def cleanup_rate_limiters():
    """
    Периодически очищает старые записи из rate limiter'ов.
    Запускается как фоновая задача.
    """
    logger.info("🧹 Rate limiter cleanup task started")
    
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)
            
            current_time = time.time()
            cleanup_threshold = current_time - 3600  # Удаляем записи старше часа
            
            # Очищаем старые записи
            users_to_remove = []
            for user_id, requests in _user_requests.items():
                # Удаляем старые запросы
                while requests and requests[0] < cleanup_threshold:
                    requests.popleft()
                
                # Если у пользователя нет активных запросов, удаляем его
                if not requests:
                    users_to_remove.append(user_id)
            
            for user_id in users_to_remove:
                _user_requests.pop(user_id, None)
                _user_last_request.pop(user_id, None)
            
            if users_to_remove:
                logger.info(f"🧹 Cleaned up {len(users_to_remove)} inactive users from rate limiter")
                
        except Exception as e:
            logger.error(f"Error in rate limiter cleanup: {e}")
            await asyncio.sleep(60)  # Пауза при ошибке

def is_rate_limited(user_id: int) -> bool:
    """
    Проверяет, не превышен ли лимит запросов для пользователя.
    
    Args:
        user_id: ID пользователя
        
    Returns:
        True, если пользователь превысил лимит
    """
    current_time = time.time()
    
    # Получаем историю запросов пользователя
    requests = _user_requests[user_id]
    
    # Удаляем старые запросы (старше минуты)
    minute_ago = current_time - 60
    while requests and requests[0] < minute_ago:
        requests.popleft()
    
    # Проверяем лимит в минуту
    if len(requests) >= MAX_REQUESTS_PER_MINUTE:
        return True
    
    # Проверяем лимит в час (примерно)
    hour_ago = current_time - 3600
    hour_requests = [req for req in requests if req > hour_ago]
    if len(hour_requests) >= MAX_REQUESTS_PER_HOUR:
        return True
    
    return False

def record_request(user_id: int) -> None:
    """
    Записывает новый запрос пользователя.
    
    Args:
        user_id: ID пользователя
    """
    current_time = time.time()
    _user_requests[user_id].append(current_time)
    _user_last_request[user_id] = current_time

def get_user_stats(user_id: int) -> Dict[str, int]:
    """
    Возвращает статистику запросов пользователя.
    
    Args:
        user_id: ID пользователя
        
    Returns:
        Словарь со статистикой
    """
    current_time = time.time()
    requests = _user_requests[user_id]
    
    # Удаляем старые запросы
    minute_ago = current_time - 60
    hour_ago = current_time - 3600
    
    minute_requests = [req for req in requests if req > minute_ago]
    hour_requests = [req for req in requests if req > hour_ago]
    
    return {
        "requests_last_minute": len(minute_requests),
        "requests_last_hour": len(hour_requests),
        "total_requests": len(requests)
    }

def reset_user_limits(user_id: int) -> None:
    """
    Сбрасывает лимиты для пользователя (для админов).
    
    Args:
        user_id: ID пользователя
    """
    _user_requests.pop(user_id, None)
    _user_last_request.pop(user_id, None)
    logger.info(f"🔄 Rate limits reset for user {user_id}")

