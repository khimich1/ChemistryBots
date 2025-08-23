import os
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# Канал для обязательной подписки. Можно задать в .env как REQUIRED_CHANNEL.
# Форматы: "@username" или числовой ID канала (например, -1001234567890).
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@himich_teacher").strip()


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    """
    Проверяет подписку пользователя на канал REQUIRED_CHANNEL.
    Возвращает True, если пользователь состоит в канале (member/administrator/creator).
    """
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        status = getattr(member, "status", None)
        return status in {"member", "administrator", "creator"}
    except Exception:
        # Если бот не админ в канале или канал приватный — будет ошибка.
        # В этом случае считаем, что пользователь НЕ подписан.
        return False


def build_subscribe_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура с кнопкой на канал и кнопкой повторной проверки подписки.
    """
    channel_link = REQUIRED_CHANNEL if str(REQUIRED_CHANNEL).startswith("@") else str(REQUIRED_CHANNEL)
    # Если у нас @username — делаем прямую ссылку
    if channel_link.startswith("@"):
        url = f"https://t.me/{channel_link.lstrip('@')}"
    else:
        # На случай числового ID — дадим просто t.me/himich_teacher как безопасный дефолт
        # Можно переопределить REQUIRED_CHANNEL в .env на @username, чтобы работала ссылка
        url = "https://t.me/himich_teacher"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Подписаться на канал", url=url)],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
        ]
    )


