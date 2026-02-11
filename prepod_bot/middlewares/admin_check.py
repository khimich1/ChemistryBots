from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from typing import Callable, Dict, Any, Awaitable
import sqlite3
import os
from config import USERS_DB, ADMIN_IDS, DB_PATH
from services.teachers import get_teacher_moniker

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
        
        # 0) Пропустим по ADMIN_IDS, если задано
        try:
            if int(user_id) in (ADMIN_IDS or []):
                return await handler(event, data)
        except Exception:
            pass

        # Проверяем регистрацию в базе admin_bot (таблица teacher)
        def _exists_in_teacher(db_path: str) -> bool:
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT 1 FROM teacher WHERE tg_id=? LIMIT 1", (int(user_id),))
                    return cur.fetchone() is not None
            except Exception:
                return False

        # 1) Прямой запрос в teacher по пути из .env (prepod_bot)
        if USERS_DB and os.path.exists(USERS_DB) and _exists_in_teacher(USERS_DB):
            return await handler(event, data)
        # 1b) Также поддержим teacher в базе ответов (test_answers.db)
        if DB_PATH and os.path.exists(DB_PATH) and _exists_in_teacher(DB_PATH):
            return await handler(event, data)
        # 2) Мягкая проверка через сервис teacher (если схема отличается)
        try:
            moniker = get_teacher_moniker(int(user_id))
            if moniker is not None:
                return await handler(event, data)
        except Exception:
            pass

        # Fallback: попробовать взять путь к users.db из admin_bot/.env (USERS_DB_PATH)
        try:
            from dotenv import dotenv_values
            repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
            admin_env_path = os.path.join(repo_root, "admin_bot", ".env")
            vals = dotenv_values(admin_env_path) if os.path.exists(admin_env_path) else {}
            alt_path = vals.get("USERS_DB_PATH")
            if alt_path and os.path.exists(alt_path) and _exists_in_teacher(alt_path):
                return await handler(event, data)
        except Exception:
            pass

        # Нет в teacher — доступ запрещён
        if isinstance(event, Message):
            try:
                await event.answer("❌ Доступ только для преподавателей, зарегистрированных через админ-бота.")
            except TelegramBadRequest:
                # Сообщение устарело/нельзя ответить — молча игнорируем
                pass
        elif isinstance(event, CallbackQuery):
            try:
                await event.answer("❌ Доступ только для преподавателей, зарегистрированных через админ-бота.", show_alert=True)
            except TelegramBadRequest:
                # Просроченный callback — попробуем отправить новое сообщение в чат
                try:
                    if event.message:
                        await event.message.answer("❌ Доступ только для преподавателей, зарегистрированных через админ-бота.")
                except Exception:
                    pass
        return
        
        # Если админ - пропускаем дальше
        return await handler(event, data)
