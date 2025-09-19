from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
import sqlite3
from config import USERS_DB

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
        
        # Проверяем регистрацию в базе admin_bot (таблица teacher)
        try:
            with sqlite3.connect(USERS_DB) as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM teacher WHERE tg_id=?", (user_id,))
                row = cur.fetchone()
                if row:
                    return await handler(event, data)
        except Exception:
            # В случае ошибки БД — безопасно запрещаем доступ
            pass

        # Нет в teacher — доступ запрещён
        if isinstance(event, Message):
            await event.answer("❌ Доступ только для преподавателей, зарегистрированных через админ-бота.")
        elif isinstance(event, CallbackQuery):
            await event.answer("❌ Доступ только для преподавателей, зарегистрированных через админ-бота.", show_alert=True)
        return
        
        # Если админ - пропускаем дальше
        return await handler(event, data)
