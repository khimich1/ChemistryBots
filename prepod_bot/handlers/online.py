from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from config import ONLINE_WINDOW_MINUTES
from services.students import (
    get_online_students, get_current_task,
    get_session_activity, get_question_details
)

router = Router()
practice_started_at = {}


def _practice_kb(user_id: int) -> ReplyKeyboardMarkup:
    started = user_id in practice_started_at
    btn = "⏹ Закончить практику" if started else "▶ Начать практику"
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=btn)]], resize_keyboard=True)


def _refresh_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="online_refresh")]
    ])


@router.message(Command("online"))
@router.message(lambda m: m.text and "ученики онлайн" in m.text.lower())
async def online_entry(m: types.Message):
    await m.answer("Раздел «Ученики онлайн».", reply_markup=_practice_kb(m.from_user.id))


@router.message(lambda m: m.text == "▶ Начать практику")
async def start_practice(m: types.Message):
    practice_started_at[m.from_user.id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await show_online_now(m)


@router.message(lambda m: m.text == "⏹ Закончить практику")
async def stop_practice(m: types.Message):
    practice_started_at.pop(m.from_user.id, None)
    await m.answer("Практика завершена.", reply_markup=_practice_kb(m.from_user.id))


@router.callback_query(lambda c: c.data == "online_refresh")
async def refresh_online(cb: types.CallbackQuery):
    await show_online_now(cb.message)
    await cb.answer()


async def show_online_now(message: types.Message):
    students = get_online_students(timeout_minutes=ONLINE_WINDOW_MINUTES)
    if not students:
        await message.answer("Никого онлайн.", reply_markup=_practice_kb(message.from_user.id))
        return

    since_ts = practice_started_at.get(message.from_user.id)
    lines = ["<b>Ученики онлайн:</b>\n"]

    for s in students:
        uid = s["user_id"]

        # Получаем имя или ID
        try:
            user = await message.bot.get_chat(uid)
            name = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
        except Exception:
            name = f"ID {uid}"

        current = get_current_task(uid)
        lines.append(f"👨‍🎓 <b>{name}</b>")

        if current:
            test_type, q_id, started_at = current
            q = get_question_details(q_id) or {}
            question_text = q.get('question', '')
            options_text = q.get('options', '')
            correct_answer = q.get('correct_answer', '')

            lines.append(
                f"📋 <b>Вопрос:</b> {question_text}\n\n"
                f"Варианты ответа:\n{options_text}\n\n"
                f"✅ <b>Правильный:</b> {correct_answer}\n"
                f"⏳ Выполняет сейчас"
            )
        else:
            lines.append("— нет активного вопроса")

        if since_ts:
            lines.append(f"/history_{uid}")
        lines.append("")

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=_refresh_kb())
    await message.answer("Управление:", reply_markup=_practice_kb(message.from_user.id))


@router.message(lambda m: m.text and m.text.startswith("/history_"))
async def show_history(m: types.Message):
    since_ts = practice_started_at.get(m.from_user.id)
    if not since_ts:
        await m.answer("Сессия не начата.", reply_markup=_practice_kb(m.from_user.id))
        return

    try:
        uid = int(m.text.split("_", 1)[1])
    except Exception:
        await m.answer("Неверная команда истории.")
        return

    try:
        user = await m.bot.get_chat(uid)
        name = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
    except Exception:
        name = f"ID {uid}"

    events = get_session_activity(uid, since_ts)
    if not events:
        await m.answer("История пуста.")
        return

    out = [f"<b>История ученика {name}</b>\nс {since_ts}\n"]

    for (test_type, q_id, started_at, answered_at, user_answer, is_correct) in events:
        q = get_question_details(q_id) or {}

        # Выбор эмодзи статуса
        if answered_at:
            status_emoji = "✅" if is_correct else "❌"
        else:
            status_emoji = "⏳"

        out.append(
            f"{status_emoji} <b>Вопрос:</b> {q.get('question','')}\n\n"
            f"Варианты ответа:\n{q.get('options','')}\n\n"
            f"Ответ ученика: <b>{user_answer or '—'}</b>\n"
            f"Правильный: <b>{q.get('correct_answer','')}</b>\n"
            f"Начал: {started_at}\n"
            f"Ответил: {answered_at or '—'}\n"
            "— — —"
        )

    await m.answer("\n".join(out), parse_mode="HTML")
