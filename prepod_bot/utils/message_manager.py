import asyncio
from typing import Dict, List


class _MessageManager:
    """
    Лёгкий менеджер эфемерных сообщений.
    - add_message(user_id, message_id): запомнить сообщение
    - delete_user_messages(bot, user_id, chat_id): удалить сохранённые (с блокировками)
    - delete_user_messages_fast(bot, user_id, chat_id): быстрое удаление без блокировок
    Ошибки удаления глушатся.
    """

    def __init__(self) -> None:
        self._user_to_message_ids: Dict[int, List[int]] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        self._max_per_user: int = 50
        self._batch_size: int = 5
        self._delay_between_batches: float = 0.05
        self._max_messages_to_delete: int = 10

    def add_message(self, user_id: int, message_id: int) -> None:
        msgs = self._user_to_message_ids.setdefault(user_id, [])
        msgs.append(message_id)
        if len(msgs) > self._max_per_user:
            del msgs[: len(msgs) - self._max_per_user]

    async def delete_user_messages(self, bot, user_id: int, chat_id: int) -> None:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            await self._delete_messages_internal(bot, user_id, chat_id)

    async def delete_user_messages_fast(self, bot, user_id: int, chat_id: int) -> None:
        await self._delete_messages_internal(bot, user_id, chat_id)

    async def _delete_messages_internal(self, bot, user_id: int, chat_id: int) -> None:
        message_ids = self._user_to_message_ids.pop(user_id, [])
        if not message_ids:
            return
        recent_messages = sorted(set(message_ids), reverse=True)[:self._max_messages_to_delete]
        for i in range(0, len(recent_messages), self._batch_size):
            batch = recent_messages[i:i + self._batch_size]
            tasks = [self._delete_single_message(bot, chat_id, mid) for mid in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            if i + self._batch_size < len(recent_messages):
                await asyncio.sleep(self._delay_between_batches)

    async def _delete_single_message(self, bot, chat_id: int, message_id: int) -> None:
        try:
            await asyncio.wait_for(
                bot.delete_message(chat_id=chat_id, message_id=message_id),
                timeout=1.0
            )
        except Exception:
            pass


message_manager = _MessageManager()


