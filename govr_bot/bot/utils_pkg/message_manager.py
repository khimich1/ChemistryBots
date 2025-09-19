import asyncio
from typing import Dict, List
import time


class _MessageManager:
    """
    Optimized in-memory tracker for ephemeral messages per user.
    
    Features:
    - Parallel message deletion with batching
    - Reduced memory usage (50 messages max per user)
    - Fast deletion mode without locks
    - Timeout protection for API calls

    - add_message(user_id, message_id): remember message to auto-delete later
    - delete_user_messages(bot, user_id, chat_id): delete and clear remembered messages (with locks)
    - delete_user_messages_fast(bot, user_id, chat_id): fast deletion without locks

    All delete errors are swallowed by design.
    """

    def __init__(self) -> None:
        self._user_to_message_ids: Dict[int, List[int]] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        self._max_per_user: int = 50  # Уменьшили с 200 до 50 для экономии памяти
        self._batch_size: int = 5     # Удаляем по 5 сообщений за раз
        self._delay_between_batches: float = 0.05  # 50мс между батчами
        self._max_messages_to_delete: int = 10     # Максимум 10 сообщений за раз

    def add_message(self, user_id: int, message_id: int) -> None:
        msgs = self._user_to_message_ids.setdefault(user_id, [])
        msgs.append(message_id)
        # Keep memory bounded
        if len(msgs) > self._max_per_user:
            del msgs[: len(msgs) - self._max_per_user]

    async def delete_user_messages(self, bot, user_id: int, chat_id: int) -> None:
        """Стандартное удаление с блокировками (для критических операций)"""
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            await self._delete_messages_internal(bot, user_id, chat_id)

    async def delete_user_messages_fast(self, bot, user_id: int, chat_id: int) -> None:
        """Быстрое удаление без блокировок (для обычных операций)"""
        await self._delete_messages_internal(bot, user_id, chat_id)

    async def _delete_messages_internal(self, bot, user_id: int, chat_id: int) -> None:
        """Внутренняя логика удаления сообщений"""
        message_ids = self._user_to_message_ids.pop(user_id, [])
        if not message_ids:
            return
            
        # Берем только последние N сообщений для быстрого удаления
        recent_messages = sorted(set(message_ids), reverse=True)[:self._max_messages_to_delete]
        
        # Удаляем батчами по 5 сообщений
        for i in range(0, len(recent_messages), self._batch_size):
            batch = recent_messages[i:i + self._batch_size]
            
            # Создаем задачи для параллельного удаления
            tasks = []
            for mid in batch:
                task = self._delete_single_message(bot, chat_id, mid)
                tasks.append(task)
            
            # Выполняем батч параллельно
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Небольшая пауза между батчами (если есть еще батчи)
            if i + self._batch_size < len(recent_messages):
                await asyncio.sleep(self._delay_between_batches)

    async def _delete_single_message(self, bot, chat_id: int, message_id: int) -> None:
        """Удаляет одно сообщение с таймаутом"""
        try:
            await asyncio.wait_for(
                bot.delete_message(chat_id=chat_id, message_id=message_id),
                timeout=1.0  # Уменьшили таймаут до 1 секунды для быстрой работы
            )
        except asyncio.TimeoutError:
            # Таймаут - просто пропускаем
            pass
        except Exception:
            # Игнорируем все остальные ошибки (сообщение уже удалено, нет прав, и т.д.)
            pass


# Singleton instance for importing
message_manager = _MessageManager()


