from aiogram import Router, types, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime
from html import escape
import asyncio

from config import ONLINE_WINDOW_MINUTES
from services.students import (
    get_online_students, get_current_task,
    get_session_activity, get_recent_activity,
    get_question_details, get_question_position,
    get_activity_updates_since, get_user_label,
)
from handlers import menu

router = Router()

# user_id преподавателя -> "YYYY-MM-DD HH:MM:SS"
practice_started_at: dict[int, str] = {}

# преподаватели, подписанные на оповещения
subscribers: set[int] = set()

# Максимальная длина текста в сообщении Telegram ~4096 символов
_TG_TEXT_LIMIT = 4096
_SAFE_LIMIT = 3800  # чуть меньше, с запасом под HTML и маркдаун

# Храним отправленные сообщения истории, чтобы удалить все по кнопке «Назад»
history_messages: dict[int, list[tuple[int, int]]] = {}


def _practice_kb(user_id: int) -> ReplyKeyboardMarkup:
    started = user_id in practice_started_at
    btn = "⏹ Закончить практику" if started else "▶ Начать практику"
    notif_btn = "🔕 Выключить оповещения" if user_id in subscribers else "🔔 Включить оповещения"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn)],
        [KeyboardButton(text=notif_btn)],
        [KeyboardButton(text="⬅️ Выход в главное меню")]
    ], resize_keyboard=True)


def _refresh_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="online_refresh")]
    ])


def _online_kb() -> InlineKeyboardMarkup:
    students = get_online_students(timeout_minutes=ONLINE_WINDOW_MINUTES, with_names=True)
    rows = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="online_refresh")]]
    for s in students:
        label = _fmt_name(s)
        rows.append([InlineKeyboardButton(text=f"📜 История: {label}", callback_data=f"hist:{s['user_id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _split_for_telegram(text: str, limit: int = _SAFE_LIMIT) -> list[str]:
    """
    Делит текст на части, безопасные по длине для Telegram.
    Стараемся резать по пустым строкам (\n\n). Если кусок всё равно длинный — режем жёстко.
    """
    parts = text.split("\n\n")
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    for part in parts:
        p = part
        add_len = (2 if buf else 0) + len(p)
        if buf_len + add_len <= limit:
            if buf:
                buf.append("")
            buf.append(p)
            buf_len += add_len
        else:
            if buf:
                chunks.append("\n\n".join(buf))
            # если отдельный абзац больше лимита — режем жёстко
            if len(p) > limit:
                s = p
                while len(s) > limit:
                    chunks.append(s[:limit])
                    s = s[limit:]
                buf = [s]
                buf_len = len(s)
            else:
                buf = [p]
                buf_len = len(p)

    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _history_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="hist_back")]
    ])


async def _send_long_html(msg: types.Message, text: str, viewer_id: int | None = None) -> None:
    chunks = _split_for_telegram(text)
    sent_messages: list[tuple[int, int]] = []
    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            sent = await msg.answer(chunk, parse_mode="HTML", reply_markup=_history_back_kb())
        else:
            sent = await msg.answer(chunk, parse_mode="HTML")
        sent_messages.append((sent.chat.id, sent.message_id))
    if viewer_id is not None:
        history_messages[viewer_id] = sent_messages


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
@router.message(StateFilter('*'), lambda m: m.text and "ученики онлайн" in m.text.lower())
async def online_entry(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Раздел «Ученики онлайн».", reply_markup=_practice_kb(m.from_user.id))
    text = _build_online_text(m.from_user.id)
    await m.answer(text, parse_mode="HTML", reply_markup=_online_kb())


@router.message(lambda m: m.text == "▶ Начать практику")
async def start_practice(m: types.Message):
    practice_started_at[m.from_user.id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = _build_online_text(m.from_user.id)
    await m.answer(text, parse_mode="HTML", reply_markup=_online_kb())
    await m.answer("Управление:", reply_markup=_practice_kb(m.from_user.id))


@router.message(lambda m: m.text == "⏹ Закончить практику")
async def stop_practice(m: types.Message):
    practice_started_at.pop(m.from_user.id, None)
    await m.answer("Практика завершена.")
    await menu.cmd_start(m)


@router.message(lambda m: m.text == "⬅️ Выход в главное меню")
async def back_to_main_menu(m: types.Message):
    """Возврат в главное меню без завершения практики"""
    await menu.cmd_start(m)


@router.callback_query(lambda c: c.data == "online_refresh")
async def refresh_online(cb: types.CallbackQuery):
    text = _build_online_text(cb.from_user.id)
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_online_kb())
    except Exception:
        pass
    await cb.answer()


@router.message(lambda m: m.text and m.text.startswith("/history_"))
async def show_history_cmd(m: types.Message):
    await _send_history(m, m.text.split("_", 1)[1] if "_" in m.text else "", m.from_user.id)


@router.callback_query(lambda c: c.data and c.data.startswith("hist:"))
async def show_history_cb(cb: types.CallbackQuery):
    uid = cb.data.split(":", 1)[1] if ":" in cb.data else ""
    await _send_history(cb.message, uid, cb.from_user.id)
    await cb.answer()


async def _send_history(msg: types.Message, uid_raw: str, viewer_id: int):
    # viewer_id — id преподавателя, нажавшего команду/кнопку
    since_ts = practice_started_at.get(viewer_id)
    try:
        uid = int(uid_raw)
    except Exception:
        await msg.answer("Неверная команда истории.")
        return

    events = (get_session_activity(uid, since_ts, with_names=False)
              if since_ts else get_recent_activity(uid, limit=20))

    if not events:
        await msg.answer("История пуста.")
        return

    title_suffix = f"с {since_ts}" if since_ts else "последние 20 событий"
    out = [f"<b>История ученика ID {uid}</b>\n{title_suffix}\n"]

    for e in events:
        q = get_question_details(e["question_id"]) or {}
        status_emoji = "✅" if e["is_correct"] else "❌" if e["answered_at"] else "⏳"

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

    await _send_long_html(msg, "\n".join(out), viewer_id)


@router.callback_query(lambda c: c.data == "hist_back")
async def history_back(cb: types.CallbackQuery):
    # Удаляем все отправленные сообщения истории для данного преподавателя
    pairs = history_messages.pop(cb.from_user.id, [])
    if not pairs:
        # Если список пуст — пробуем удалить текущее
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.answer()
        return

    for chat_id, message_id in pairs:
        try:
            await cb.bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    await cb.answer()


@router.message(lambda m: m.text in ("🔔 Включить оповещения", "🔕 Выключить оповещения"))
async def toggle_notifications(m: types.Message):
    uid = m.from_user.id
    if uid in subscribers:
        subscribers.remove(uid)
        await m.answer("Оповещения выключены.", reply_markup=_practice_kb(uid))
    else:
        subscribers.add(uid)
        await m.answer("Оповещения включены. Бот будет присылать новые события учеников.", reply_markup=_practice_kb(uid))


async def start_notifier(bot: Bot, poll_interval_sec: int = 10):
    """
    Фоновая задача: периодически проверяет новые события и рассылает подписчикам.
    """
    last_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    while True:
        try:
            await asyncio.sleep(poll_interval_sec)
            events = get_activity_updates_since(last_ts)
            if not events:
                continue

            # обновляем last_ts
            for ev in events:
                for ts in (ev.get("answered_at") or "", ev.get("started_at") or ""):
                    if ts and ts > last_ts:
                        last_ts = ts

            for ev in events:
                label = get_user_label(ev["user_id"])
                if ev.get("answered_at"):
                    status = "✅ Верно" if ev.get("is_correct") else "❌ Неверно"
                    msg = (
                        f"{status} — {label}\n"
                        f"Задание №{ev.get('test_type')}, вопрос ID {ev.get('question_id')}\n"
                        f"Ответ: {ev.get('user_answer') or '—'}"
                    )
                else:
                    msg = (
                        f"▶ {label} начал вопрос\n"
                        f"Задание №{ev.get('test_type')}, вопрос ID {ev.get('question_id')}"
                    )

                for teacher_id in list(subscribers):
                    try:
                        await bot.send_message(teacher_id, msg)
                    except Exception:
                        pass
        except Exception:
            await asyncio.sleep(poll_interval_sec)
