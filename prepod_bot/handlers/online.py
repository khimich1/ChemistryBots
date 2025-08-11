from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from config import ONLINE_WINDOW_MINUTES
from services.students import (
    get_online_students, get_current_task,
    get_session_activity, get_question_details
)
from handlers import menu  # главное меню

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
    await m.answer("Практика завершена.")
    await menu.start_menu(m)  # возврат в главное меню


@router.callback_query(lambda c: c.data == "online_refresh")
async def refresh_online(cb: types.CallbackQuery):
    await show_online_now(cb.message)
    await cb.answer()


async def show_online_now(message: types.Message):
    students = get_online_students(timeout_minutes=ONLINE_WINDOW_MINUTES, with_names=True)
    if not students:
        await message.answer("Никого онлайн.", reply_markup=_practice_kb(message.from_user.id))
        return

    since_ts = practice_started_at.get(message.from_user.id)
    lines = ["<b>Ученики онлайн:</b>\n"]

    for s in students:
        name = f"@{s['username']}" if s['username'] else (s['full_name'] or f"ID {s['user_id']}")

        current = get_current_task(s["user_id"])
        lines.append(f"👨‍🎓 <b>{name}</b>")

        if current:
            _, q_id, _ = current
            q = get_question_details(q_id) or {}
            lines.append(
                f"📋 <b>Вопрос:</b> {q.get('question','')}\n\n"
                f"Варианты ответа:\n{q.get('options','')}\n\n"
                f"✅ <b>Правильный:</b> {q.get('correct_answer','')}\n"
                f"⏳ Выполняет сейчас"
            )
        else:
            lines.append("— нет активного вопроса")

        if since_ts:
            lines.append(f"/history_{s['user_id']}")
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

    events = get_session_activity(uid, since_ts, with_names=True)
    if not events:
        await m.answer("История пуста.")
        return

    student_name = f"@{events[0]['username']}" if events[0]['username'] else (events[0]['full_name'] or f"ID {uid}")
    out = [f"<b>История ученика {student_name}</b>\nс {since_ts}\n"]

    for e in events:
        q = get_question_details(e["question_id"]) or {}
        status_emoji = "✅" if e["is_correct"] else "❌" if e["answered_at"] else "⏳"
        out.append(
            f"{status_emoji} <b>Вопрос:</b> {q.get('question','')}\n\n"
            f"Варианты ответа:\n{q.get('options','')}\n\n"
            f"Ответ ученика: <b>{e['user_answer'] or '—'}</b>\n"
            f"Правильный: <b>{q.get('correct_answer','')}</b>\n"
            f"Начал: {e['started_at']}\n"
            f"Ответил: {e['answered_at'] or '—'}\n"
            "— — —"
        )

    await m.answer("\n".join(out), parse_mode="HTML")
