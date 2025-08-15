from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from html import escape

from config import ONLINE_WINDOW_MINUTES
from services.students import (
    get_online_students, get_current_task,
    get_session_activity, get_recent_activity,
    get_question_details, get_question_position
)
from handlers import menu

router = Router()

# user_id преподавателя -> "YYYY-MM-DD HH:MM:SS"
practice_started_at: dict[int, str] = {}


def _practice_kb(user_id: int) -> ReplyKeyboardMarkup:
    started = user_id in practice_started_at
    btn = "⏹ Закончить практику" if started else "▶ Начать практику"
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=btn)]], resize_keyboard=True)


def _refresh_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="online_refresh")]
    ])


def _fmt_name(student: dict) -> str:
    username = student.get("username")
    full_name = student.get("full_name")
    if username:
        return f"@{escape(username)}"
    if full_name:
        return escape(full_name)
    return f"ID {student['user_id']}"


def _fmt_question(q: dict) -> str:
    question = escape(q.get("question", "") or "")
    options = escape(q.get("options", "") or "")
    correct = escape(q.get("correct_answer", "") or "")
    return (
        f"📘 <b>Вопрос:</b> {question}\n\n"
        f"Варианты ответа:\n{options}\n\n"
        f"✅ <b>Правильный:</b> {correct}"
    )


def _fmt_header(test_type: int | None, pos: int | None, total: int | None) -> str:
    parts = []
    if test_type is not None:
        parts.append(f"🧪 <b>Задание №:</b> {test_type}")
    if pos is not None and total is not None:
        parts.append(f"❓ <b>Вопрос:</b> {pos} из {total}")
    return "\n".join(parts)


def _build_online_text(viewer_id: int) -> str:
    students = get_online_students(timeout_minutes=ONLINE_WINDOW_MINUTES, with_names=True)
    if not students:
        return "Никого онлайн."
    lines = ["<b>Ученики онлайн:</b>\n"]
    for s in students:
        name = _fmt_name(s)
        lines.append(f"👨‍🎓 <b>{name}</b>")

        current = get_current_task(s["user_id"])
        if current:
            test_type, q_id, _ = current
            # Заголовок с типом и позиционкой
            pos, total = get_question_position(s["user_id"], test_type, q_id)
            header = _fmt_header(test_type, pos, total)
            if header:
                lines.append(header)

            # Текст вопроса
            q = get_question_details(q_id) or {}
            if q:
                lines.append(_fmt_question(q))
                lines.append("⏳ Выполняет сейчас")
            else:
                lines.append(f"📋 Вопрос ID {q_id}\n(детали временно недоступны)")
        else:
            lines.append("— нет активного вопроса")

        # Ссылка истории ВСЕГДА
        lines.append(f"/history_{s['user_id']}")
        lines.append("")
    return "\n".join(lines)


@router.message(Command("online"))
@router.message(lambda m: m.text and "ученики онлайн" in m.text.lower())
async def online_entry(m: types.Message):
    await m.answer("Раздел «Ученики онлайн».", reply_markup=_practice_kb(m.from_user.id))
    text = _build_online_text(m.from_user.id)
    await m.answer(text, parse_mode="HTML", reply_markup=_refresh_kb())


@router.message(lambda m: m.text == "▶ Начать практику")
async def start_practice(m: types.Message):
    practice_started_at[m.from_user.id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = _build_online_text(m.from_user.id)
    await m.answer(text, parse_mode="HTML", reply_markup=_refresh_kb())
    await m.answer("Управление:", reply_markup=_practice_kb(m.from_user.id))


@router.message(lambda m: m.text == "⏹ Закончить практику")
async def stop_practice(m: types.Message):
    practice_started_at.pop(m.from_user.id, None)
    await m.answer("Практика завершена.")
    await menu.cmd_start(m)


@router.callback_query(lambda c: c.data == "online_refresh")
async def refresh_online(cb: types.CallbackQuery):
    text = _build_online_text(cb.from_user.id)
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_refresh_kb())
    except Exception:
        pass
    await cb.answer()


@router.message(lambda m: m.text and m.text.startswith("/history_"))
async def show_history(m: types.Message):
    since_ts = practice_started_at.get(m.from_user.id)

    try:
        uid = int(m.text.split("_", 1)[1])
    except Exception:
        await m.answer("Неверная команда истории.")
        return

    # если практика идёт — с начала сессии; иначе последние 20
    events = (get_session_activity(uid, since_ts, with_names=False)
              if since_ts else get_recent_activity(uid, limit=20))

    if not events:
        await m.answer("История пуста.")
        return

    title_suffix = f"с {since_ts}" if since_ts else "последние 20 событий"
    out = [f"<b>История ученика ID {uid}</b>\n{title_suffix}\n"]

    for e in events:
        q = get_question_details(e["question_id"]) or {}
        status_emoji = "✅" if e["is_correct"] else "❌" if e["answered_at"] else "⏳"

        # Заголовок с «Задание №» и «Вопрос: n из m»
        pos, total = get_question_position(uid, e["test_type"], e["question_id"])
        header = _fmt_header(e["test_type"], pos, total)
        if header:
            out.append(header)

        if q:
            out.append(
                f"{status_emoji} {_fmt_question(q)}\n"
                f"Ответ ученика: <b>{escape(e['user_answer'] or '—')}</b>\n"
                f"Начал: {e['started_at']}\n"
                f"Ответил: {e['answered_at'] or '—'}\n"
                "— — —"
            )
        else:
            out.append(
                f"{status_emoji} Вопрос ID {e['question_id']}\n"
                f"Ответ ученика: <b>{escape(e['user_answer'] or '—')}</b>\n"
                f"Начал: {e['started_at']}\n"
                f"Ответил: {e['answered_at'] or '—'}\n"
                "— — —"
            )

    await m.answer("\n".join(out), parse_mode="HTML")
