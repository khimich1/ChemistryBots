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
from services.groups import list_group_tasks, get_work_group_members, get_all_group_numbers
from utils.message_manager import message_manager

router = Router()

# user_id преподавателя -> "YYYY-MM-DD HH:MM:SS"
practice_started_at: dict[int, str] = {}

# преподаватели, подписанные на оповещения
subscribers: set[int] = set()

# выбранный фильтр по группе: teacher_id -> group_no | None
group_filter: dict[int, int | None] = {}

# кэш назначенных вопрос ID для группы: (teacher_id, group_no) -> set(qid)
_group_qids_cache: dict[tuple[int, int], set[int]] = {}
# кэш источников для группы: (teacher_id, group_no) -> { 'teacher': set[int], 'ege': set[int], 'oge': set[int] }
_group_sources_cache: dict[tuple[int, int], dict[str, set[int]]] = {}

# Максимальная длина текста в сообщении Telegram ~4096 символов
_TG_TEXT_LIMIT = 4096
_SAFE_LIMIT = 3800  # чуть меньше, с запасом под HTML и маркдаун

# Храним отправленные сообщения истории, чтобы удалить все по кнопке «Назад»
history_messages: dict[int, list[tuple[int, int]]] = {}
online_image_messages: dict[int, list[tuple[int, int]]] = {}


def _practice_kb(user_id: int) -> ReplyKeyboardMarkup:
    started = user_id in practice_started_at
    btn = "⏹ Закончить практику" if started else "▶ Начать практику"
    notif_btn = "🔕 Выключить оповещения" if user_id in subscribers else "🔔 Включить оповещения"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn)],
        [KeyboardButton(text=notif_btn)],
        [KeyboardButton(text="⬅️ Выход в главное меню")]
    ], resize_keyboard=True)


def _refresh_kb(viewer_id: int) -> InlineKeyboardMarkup:
    current = group_filter.get(viewer_id)
    label = "Все" if current is None else f"Группа {current}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="online_refresh")],
        [InlineKeyboardButton(text=f"🎯 Фильтр: {label}", callback_data="online_filter")],
    ])


def _online_kb(viewer_id: int) -> InlineKeyboardMarkup:
    students = get_online_students(timeout_minutes=ONLINE_WINDOW_MINUTES, with_names=True)
    current = group_filter.get(viewer_id)
    label = "Все" if current is None else f"Группа {current}"
    rows = [
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="online_refresh")],
        [InlineKeyboardButton(text=f"🎯 Фильтр: {label}", callback_data="online_filter")],
    ]
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


def _parse_qids_from_items(items: str) -> list[int]:
    parts = [p.strip() for p in (items or "").split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try:
            _, sid = p.split(":", 1)
            out.append(int(str(sid).strip()))
        except Exception:
            continue
    return out


def _get_group_qids(viewer_id: int, group_no: int) -> set[int]:
    key = (int(viewer_id), int(group_no))
    if key in _group_qids_cache:
        return _group_qids_cache[key]
    qids: set[int] = set()
    try:
        tasks = list_group_tasks(int(group_no), teacher_id=int(viewer_id))
        for t in tasks:
            qids.update(_parse_qids_from_items(t.get("items") or ""))
    except Exception:
        qids = set()
    _group_qids_cache[key] = qids
    return qids


def _get_group_sources(viewer_id: int, group_no: int) -> dict[str, set[int]]:
    """Возвращает словарь множеств id по источнику: {'teacher', 'ege', 'oge'} для назначенных группе задач."""
    key = (int(viewer_id), int(group_no))
    if key in _group_sources_cache:
        return _group_sources_cache[key]
    src = {"teacher": set(), "ege": set(), "oge": set()}
    try:
        tasks = list_group_tasks(int(group_no), teacher_id=int(viewer_id))
        for t in tasks:
            items = (t.get("items") or "").split(",")
            for part in items:
                p = part.strip()
                if not p:
                    continue
                if ":" in p:
                    prefix, sid = p.split(":", 1)
                    try:
                        qid = int(str(sid).strip())
                    except Exception:
                        continue
                    pref = (prefix or "").strip().lower()
                    if pref in src:
                        src[pref].add(qid)
                    else:
                        src["ege"].add(qid)
                else:
                    # без префикса считаем как ege
                    try:
                        qid = int(p)
                        src["ege"].add(qid)
                    except Exception:
                        continue
    except Exception:
        pass
    _group_sources_cache[key] = src
    return src


def _build_online_text(viewer_id: int) -> str:
    students = get_online_students(timeout_minutes=ONLINE_WINDOW_MINUTES, with_names=True)
    current_group = group_filter.get(viewer_id)
    # Если выбран фильтр по группе — оставим только участников группы И вопросы из назначенных qids
    member_set: set[int] | None = None
    qid_set: set[int] | None = None
    if current_group is not None:
        try:
            member_set = set(get_work_group_members(int(current_group), teacher_id=int(viewer_id)))
        except Exception:
            member_set = set()
        qid_set = _get_group_qids(viewer_id, int(current_group))

    if not students:
        header = "<b>Ученики онлайн:</b>\n"
        if current_group is not None:
            header += f"(фильтр: группа {current_group})\n"
        return header + "Никого онлайн."

    lines = ["<b>Ученики онлайн:</b>"]
    if current_group is not None:
        lines.append(f"(фильтр: группа {current_group})")
        lines.append("")
    for s in students:
        name = _fmt_name(s)
        # Фильтрация по группе, если включена
        if member_set is not None and int(s["user_id"]) not in member_set:
            # не участник выбранной группы
            continue
        lines.append(f"👨‍🎓 <b>{name}</b>")

        current = get_current_task(s["user_id"])
        if current:
            test_type, q_id, _ = current
            # Если включён фильтр по группе — проверяем, что вопрос относится к назначенным
            if qid_set is not None and int(q_id) not in qid_set:
                # пропускаем записи не из набора
                lines.pop()  # удаляем добавленную шапку ученика
                continue
            # Заголовок с типом и позиционкой
            pos, total = get_question_position(s["user_id"], test_type, q_id)
            header = _fmt_header(test_type, pos, total)
            if header:
                lines.append(header)

            # Текст вопроса (если пустой — попробуем показать фото отдельно внизу)
            # Приоритет teacher-источника: 1) если test_type >= 20000, 2) если выбран фильтр по группе и q_id назначен как teacher
            q = {}
            prefer_teacher = False
            try:
                prefer_teacher = prefer_teacher or (int(test_type) >= 20000)
            except Exception:
                pass
            if current_group is not None and not prefer_teacher:
                sources = _get_group_sources(viewer_id, int(current_group))
                if int(q_id) in sources.get("teacher", set()):
                    prefer_teacher = True
            if prefer_teacher:
                try:
                    from govr_bot.bot.services.test_sql_teacher import get_question_by_id as _teacher_q
                    q = _teacher_q(int(q_id)) or {}
                except Exception:
                    q = {}
            if not q:
                q = get_question_details(q_id) or {}
            if not q:
                # Фолбэк: пробуем teacher-БД даже без фильтра группы
                try:
                    from govr_bot.bot.services.test_sql_teacher import get_question_by_id as _teacher_q
                    q = _teacher_q(int(q_id)) or {}
                except Exception:
                    q = {}
            has_text = bool((q.get("question") or "").strip())
            if has_text:
                lines.append(_fmt_question(q))
                lines.append("⏳ Выполняет сейчас")
            else:
                # Пометим, что вопрос как изображение; реальные фото отправим после текста
                lines.append("📷 Вопрос прислан как изображение — см. фото ниже")
        else:
            lines.append("— нет активного вопроса")

        # Ссылка истории ВСЕГДА
        lines.append(f"/history_{s['user_id']}")
        lines.append("")
    return "\n".join(lines)


async def _send_online_images(msg: types.Message, viewer_id: int) -> None:
    """После отправки текста онлайн-ленты — отдельно отправляем фото для вопросов без текста."""
    # Удалим предыдущие фото
    for chat_id, message_id in online_image_messages.pop(viewer_id, []):
        try:
            await msg.bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    students = get_online_students(timeout_minutes=ONLINE_WINDOW_MINUTES, with_names=True)
    current_group = group_filter.get(viewer_id)
    member_set: set[int] | None = None
    qid_set: set[int] | None = None
    if current_group is not None:
        try:
            member_set = set(get_work_group_members(int(current_group), teacher_id=int(viewer_id)))
        except Exception:
            member_set = set()
        qid_set = _get_group_qids(viewer_id, int(current_group))

    from aiogram.types import BufferedInputFile, InputMediaPhoto
    sent_pairs: list[tuple[int, int]] = []
    for s in students:
        if member_set is not None and int(s["user_id"]) not in member_set:
            continue
        cur = get_current_task(s["user_id"])
        if not cur:
            continue
        _, q_id, _ = cur
        if qid_set is not None and int(q_id) not in qid_set:
            continue
        # Получим вопрос с изображением из баз govr-бота
        q_img = None
        try:
            from govr_bot.bot.services.test_sql import get_question_with_image as _ege_q
            q_img = _ege_q(int(q_id))
        except Exception:
            q_img = None
        if not q_img:
            try:
                from govr_bot.bot.services.test_sql_oge import get_question_with_image as _oge_q
                q_img = _oge_q(int(q_id))
            except Exception:
                q_img = None
        if not q_img:
            try:
                from govr_bot.bot.services.test_sql_teacher import get_question_with_image as _tch_q
                q_img = _tch_q(int(q_id))
            except Exception:
                q_img = None
        # Если у вопроса есть осмысленный текст — пропускаем (его уже показали как текст)
        if q_img and (q_img.get("question") or "").strip():
            continue
        # Соберём изображения
        photos = []
        if q_img and q_img.get("image"):
            photos = [q_img["image"]]
        elif q_img and q_img.get("images"):
            photos = list(q_img["images"])[:10]
        if not photos:
            continue
        name = _fmt_name(s)
        caption = f"👨‍🎓 {name}\nВыполняет сейчас (вопрос как изображение)"
        try:
            if len(photos) == 1:
                bf = BufferedInputFile(file=photos[0]["data"], filename=photos[0].get("filename", "question.png"))
                sent = await msg.answer_photo(photo=bf, caption=caption)
                sent_pairs.append((sent.chat.id, sent.message_id))
            else:
                media = [InputMediaPhoto(media=BufferedInputFile(file=photos[0]["data"], filename=photos[0].get("filename", "q.png")), caption=caption)]
                for p in photos[1:]:
                    media.append(InputMediaPhoto(media=BufferedInputFile(file=p["data"], filename=p.get("filename", "q.png"))))
                messages = await msg.bot.send_media_group(msg.chat.id, media)
                for m in messages:
                    sent_pairs.append((m.chat.id, m.message_id))
        except Exception:
            continue

    if sent_pairs:
        online_image_messages[viewer_id] = sent_pairs


@router.message(Command("online"))
@router.message(StateFilter('*'), lambda m: m.text and "ученики онлайн" in m.text.lower())
async def online_entry(m: types.Message, state: FSMContext):
    await state.clear()
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    sent0 = await m.answer("Раздел «Ученики онлайн».", reply_markup=_practice_kb(m.from_user.id))
    text = _build_online_text(m.from_user.id)
    sent1 = await m.answer(text, parse_mode="HTML", reply_markup=_online_kb(m.from_user.id))
    try:
        message_manager.add_message(m.from_user.id, sent0.message_id)
        message_manager.add_message(m.from_user.id, sent1.message_id)
    except Exception:
        pass
    # Отправим изображения, если у вопросов нет текста
    await _send_online_images(m, m.from_user.id)


@router.message(lambda m: m.text == "▶ Начать практику")
async def start_practice(m: types.Message):
    practice_started_at[m.from_user.id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = _build_online_text(m.from_user.id)
    sent1 = await m.answer(text, parse_mode="HTML", reply_markup=_online_kb(m.from_user.id))
    sent2 = await m.answer("Управление:", reply_markup=_practice_kb(m.from_user.id))
    try:
        message_manager.add_message(m.from_user.id, sent1.message_id)
        message_manager.add_message(m.from_user.id, sent2.message_id)
    except Exception:
        pass


@router.message(lambda m: m.text == "⏹ Закончить практику")
async def stop_practice(m: types.Message):
    practice_started_at.pop(m.from_user.id, None)
    sent = await m.answer("Практика завершена.")
    try:
        message_manager.add_message(m.from_user.id, sent.message_id)
    except Exception:
        pass
    await menu.cmd_start(m)


@router.message(lambda m: m.text == "⬅️ Выход в главное меню")
async def back_to_main_menu(m: types.Message):
    """Возврат в главное меню без завершения практики"""
    await menu.cmd_start(m)


@router.callback_query(lambda c: c.data == "online_refresh")
async def refresh_online(cb: types.CallbackQuery):
    text = _build_online_text(cb.from_user.id)
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_online_kb(cb.from_user.id))
    except Exception:
        pass
    await cb.answer()
    # Переотправим изображения для вопросов без текста
    await _send_online_images(cb.message, cb.from_user.id)


@router.callback_query(lambda c: c.data == "online_filter")
async def open_online_filter(cb: types.CallbackQuery):
    """Показать выбор группы для фильтра «Ученики онлайн»"""
    await cb.answer()
    rows: list[list[InlineKeyboardButton]] = []
    # Кнопка Все
    rows.append([InlineKeyboardButton(text="Все группы", callback_data="online_filter_set:all")])
    # Список групп, где у преподавателя есть участники
    try:
        groups = get_all_group_numbers()
        for g in groups:
            members = get_work_group_members(int(g), teacher_id=int(cb.from_user.id))
            if not members:
                continue
            rows.append([InlineKeyboardButton(text=f"Группа {g}", callback_data=f"online_filter_set:{g}")])
    except Exception:
        pass
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="online_refresh")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        try:
            await cb.message.edit_text(_build_online_text(cb.from_user.id), parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass


@router.callback_query(lambda c: c.data and c.data.startswith("online_filter_set:"))
async def set_online_filter(cb: types.CallbackQuery):
    try:
        arg = cb.data.split(":", 1)[1]
    except Exception:
        await cb.answer()
        return
    if arg == "all":
        group_filter[cb.from_user.id] = None
    else:
        try:
            group_filter[cb.from_user.id] = int(arg)
        except Exception:
            group_filter[cb.from_user.id] = None
    # Обновим текст и клавиатуру
    text = _build_online_text(cb.from_user.id)
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=_online_kb(cb.from_user.id))
    except Exception:
        pass
    await cb.answer("Фильтр применён")


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
            # выполняем синхронный запрос к БД в отдельном потоке, чтобы не блокировать event loop
            events = await asyncio.to_thread(get_activity_updates_since, last_ts)
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
                        # лёгкий троттлинг, чтобы избежать локальных всплесков
                        await asyncio.sleep(0.03)
                    except Exception as e:
                        # логируем, чтобы видеть реальные сбои
                        try:
                            import logging
                            logging.getLogger("prepod_bot").warning(f"notify send failed to {teacher_id}: {e}")
                        except Exception:
                            pass
        except Exception as e:
            try:
                import logging
                logging.getLogger("prepod_bot").exception(f"notifier loop error: {e}")
            except Exception:
                pass
            await asyncio.sleep(poll_interval_sec)
