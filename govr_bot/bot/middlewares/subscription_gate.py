from typing import Any, Callable, Awaitable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from bot.services.subscription import is_user_subscribed, build_subscribe_kb
from bot.utils_pkg_new.logger import log_error


class SubscriptionGateMiddleware(BaseMiddleware):
    """
    Глобальная проверка подписки. Пропускает:
    - команды /start, /help, /menu
    - любые callback'и с данными "check_sub" (для повторной проверки)
    Остальные апдейты блокирует для неподписанных пользователей и показывает
    приглашение подписаться.
    """

    def __init__(self, enabled: bool = True):
        super().__init__()
        self.enabled = enabled

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        if not self.enabled:
            return await handler(event, data)

        # CallbackQuery с кнопкой "Проверить подписку" всегда пропускаем до хендлера
        if isinstance(event, CallbackQuery):
            if (event.data or "") == "check_sub":
                return await handler(event, data)
            user_id = event.from_user.id
            bot = event.bot
            if await is_user_subscribed(bot, user_id):
                return await handler(event, data)
            try:
                await event.message.answer(
                    "Чтобы пользоваться ботом, подпишись на канал и нажми 'Проверить подписку'.",
                    reply_markup=build_subscribe_kb(),
                )
            except TelegramForbiddenError as e:
                # Пользователь заблокировал бота
                log_error(e, "User blocked bot", user_id=user_id)
                # Пытаемся отправить через callback
                try:
                    await event.answer("Пользователь заблокировал бота", show_alert=True)
                except Exception as callback_error:
                    log_error(callback_error, "Failed to send callback alert", user_id=user_id)
            except TelegramBadRequest as e:
                # Неправильный запрос (например, неправильная клавиатура)
                log_error(e, "Bad request in subscription gate", user_id=user_id)
                # Отправляем без клавиатуры
                try:
                    await event.message.answer("Подпишись на канал для доступа к боту.")
                except Exception as fallback_error:
                    log_error(fallback_error, "Failed to send fallback message", user_id=user_id)
            except TelegramAPIError as e:
                # Проблемы с Telegram API
                log_error(e, "Telegram API error in subscription gate", user_id=user_id)
            except Exception as e:
                # Неожиданные ошибки
                log_error(e, "Unexpected error in subscription gate", user_id=user_id)
            return

        # Message: пропускаем базовые команды
        if isinstance(event, Message):
            text = (event.text or "").strip().lower()
            if text.startswith("/start") or text.startswith("/help") or text.startswith("/menu"):
                return await handler(event, data)

            # Если подписан — пускаем дальше
            bot = event.bot
            user_id = event.from_user.id
            if await is_user_subscribed(bot, user_id):
                return await handler(event, data)

            # Иначе — просим подписаться
            try:
                await event.answer(
                    "Доступ только для подписчиков канала. Подпишись и нажми 'Проверить подписку'.",
                    reply_markup=build_subscribe_kb(),
                )
            except TelegramForbiddenError as e:
                # Пользователь заблокировал бота
                log_error(e, "User blocked bot (message)", user_id=user_id)
            except TelegramBadRequest as e:
                # Неправильный запрос
                log_error(e, "Bad request in subscription gate (message)", user_id=user_id)
                # Отправляем без клавиатуры
                try:
                    await event.answer("Доступ только для подписчиков канала.")
                except Exception as fallback_error:
                    log_error(fallback_error, "Failed to send fallback message (message)", user_id=user_id)
            except TelegramAPIError as e:
                # Проблемы с Telegram API
                log_error(e, "Telegram API error in subscription gate (message)", user_id=user_id)
            except Exception as e:
                # Неожиданные ошибки
                log_error(e, "Unexpected error in subscription gate (message)", user_id=user_id)
            return

        # Остальные типы обновлений пропустим без проверки
        return await handler(event, data)


