import asyncio
from typing import Dict, List


class _MessageManager:
    """
    Lightweight in-memory tracker for ephemeral messages per user.

    - add_message(user_id, message_id): remember message to auto-delete later
    - delete_user_messages(bot, user_id, chat_id): delete and clear remembered messages

    All delete errors are swallowed by design.
    """

    def __init__(self) -> None:
        self._user_to_message_ids: Dict[int, List[int]] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        self._max_per_user: int = 200

    def add_message(self, user_id: int, message_id: int) -> None:
        msgs = self._user_to_message_ids.setdefault(user_id, [])
        msgs.append(message_id)
        # Keep memory bounded
        if len(msgs) > self._max_per_user:
            del msgs[: len(msgs) - self._max_per_user]

    async def delete_user_messages(self, bot, user_id: int, chat_id: int) -> None:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            message_ids = self._user_to_message_ids.pop(user_id, [])
            if not message_ids:
                return
            # Delete newest first to reduce chance of "message to delete not found"
            for mid in sorted(set(message_ids), reverse=True):
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    # Ignore all deletion errors by design
                    pass


# Singleton instance for importing
message_manager = _MessageManager()


