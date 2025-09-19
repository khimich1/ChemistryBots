from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from config import ADMIN_IDS

class AdminCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Проверяем, что пользователь - админ
        user_id = event.from_user.id if event.from_user else None
        
        if not user_id:
            return
        
        # Если ADMIN_IDS не задан, разрешаем всем
        if not ADMIN_IDS:
            return await handler(event, data)
        
        # Проверяем, что пользователь в списке админов
        if user_id not in ADMIN_IDS:
            if isinstance(event, Message):
                await event.answer("❌ У вас нет прав для использования этого бота.")
            elif isinstance(event, CallbackQuery):
                await event.answer("❌ У вас нет прав для использования этого бота.", show_alert=True)
            return
        
        # Если админ - пропускаем дальше
        return await handler(event, data)
