from aiogram import Router, types
import re
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
import contextlib
from keyboards import (
    get_teacher_keyboard,
    get_students_keyboard,
    get_manage_groups_keyboard,
    get_group_numbers_keyboard,
    get_group_pick_keyboard,
    get_group_members_keyboard,
    get_task_method_keyboard,
    get_task_types_keyboard,
    get_variant_list_keyboard,
    get_group_tasks_kb,
    get_exam_pick_keyboard,
    get_test_types_list_keyboard,
    get_type_ids_keyboard,
)
from services.acquisition import get_ad_stats
from services.students import get_all_students
from services.teachers import get_teacher_moniker
from services.lessons import get_lessons_in_week
from services.lessons import add_lesson
from services.groups import (
    add_student_to_group,
    is_student_in_group,
    get_all_students_with_plans,
    add_user_to_work_group,
    find_user_id_by_username,
    get_all_group_numbers,
    get_work_group_members,
    broadcast_message_to_group_via_govr,
    send_message_to_user_via_govr,
    resolve_user_id_from_target,
    create_group_task,
    list_group_tasks,
    delete_group_task,
    get_group_task_by_id,
    get_question_ids_by_filename,
    get_question_ids_by_type,
    remove_user_from_work_group,
    compute_group_task_results,
)
from aiogram.fsm.context import FSMContext
from config import DEEPLINK_HINT
from states import StudentsList, WorkGroups
from services.pdf_export import render_questions_to_pdf
from keyboards import get_pick_students_for_day_kb
from datetime import datetime as _dt
from utils.message_manager import message_manager

router = Router()
# Локальные состояния для раздела расписания
class ScheduleStates(StatesGroup):
    waiting_change_time = State()
    waiting_notify_minutes = State()


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    moniker = get_teacher_moniker(tg_id) or (message.from_user.full_name or "")
    greeting_name = moniker.strip() or "Коллега"
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    sent = await message.answer(
        f"Здравствуйте, {greeting_name}! Выберите действие:",
        reply_markup=get_teacher_keyboard()
    )
    message_manager.add_message(message.from_user.id, sent.message_id)

# ── Расписание (локальный календарь) ──────────────────────────────────────────────────────────────────────────────

@router.message(StateFilter('*'), lambda m: m.text == "📅 Расписание")
async def schedule_entry(message: types.Message, state: FSMContext):
    """Точка входа в расписание: показываем локальную неделю."""
    await state.clear()
    await _show_week_schedule(message, state, tg_id=message.from_user.id)


def _unused():
    pass


def _week_inline_kb_unused():
    return types.InlineKeyboardMarkup(inline_keyboard=[])

async def _add_temp_msg(state: FSMContext, msg_id: int) -> None:
    try:
        data = await state.get_data()
        tmp = list(data.get("tmp_msgs") or [])
        tmp.append(int(msg_id))
        await state.update_data(tmp_msgs=tmp)
    except Exception:
        pass

async def _clear_temp_msgs(message: types.Message, state: FSMContext) -> None:
    try:
        data = await state.get_data()
        tmp = list(data.get("tmp_msgs") or [])
        if tmp:
            for mid in tmp:
                with contextlib.suppress(Exception):
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=int(mid))
        await state.update_data(tmp_msgs=[])
    except Exception:
        pass

async def _focus_day_menu_only(message: types.Message, state: FSMContext) -> None:
    """Удаляет все сообщения ниже сообщения дня, оставляя только верхнее окно с кнопками.
    Также удаляет недельные сообщения, если они остались.
    """
    try:
        data = await state.get_data()
        day_msg_id = int(data.get("day_menu_msg_id")) if data.get("day_menu_msg_id") else None
        if day_msg_id:
            # Удалим всё ниже day_msg_id до текущего
            cur_id = message.message_id
            for mid in range(cur_id, day_msg_id, -1):
                with contextlib.suppress(Exception):
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=mid)
        # Удалим недельный текст/клавиатуру, если ещё есть
        week_text = data.get("week_text_msg_id")
        week_kb = data.get("week_kb_msg_id")
        if week_text:
            with contextlib.suppress(Exception):
                await message.bot.delete_message(message.chat.id, int(week_text))
            await state.update_data(week_text_msg_id=None)
        if week_kb:
            with contextlib.suppress(Exception):
                await message.bot.delete_message(message.chat.id, int(week_kb))
            await state.update_data(week_kb_msg_id=None)
    except Exception:
        pass
async def _rebuild_day_menu(message: types.Message, msg_id: int, day: str) -> None:
    """Переcобирает клавиатуру списка занятий в сообщении дня (msg_id).
    Оставляет текст-заголовок как есть, меняет только inline-клавиатуру под ним.
    """
    from datetime import datetime as _datetime
    try:
        d = _datetime.strptime(day, "%Y-%m-%d")
    except Exception:
        return
    # Собираем заново список занятий
    try:
        from services.lessons import list_lessons_by_day
        lessons = list_lessons_by_day(message.from_user.id, day=day)
    except Exception:
        lessons = []
    rows: list[list[types.InlineKeyboardButton]] = []
    rows.append([types.InlineKeyboardButton(text="➕ Добавить занятия до 30 мая", callback_data=f"add_until_menu:{day}")])
    # Сортировка занятий по времени начала
    def _tkey(v: str | None) -> int:
        try:
            s = (v or "").strip()
            hh, mm = s.split(":", 1)
            return int(hh) * 60 + int(mm)
        except Exception:
            return 24 * 60 + 1
    if lessons:
        lessons = sorted(lessons, key=lambda l: _tkey(l.get('start')))
        for l in lessons:
            start = (l.get('start') or '').strip()
            end = (l.get('end') or '').strip()
            who_raw = (l.get("target") or "").strip()
            who = f"Группа {who_raw.lstrip('# ').strip()}" if l.get("kind") == "group" else (who_raw or "Ученик")
            label = f"{start}-{end} {who}"
            rows.append([types.InlineKeyboardButton(text=label, callback_data=f"open_lesson:{l.get('id')}")])
    # Кнопка Назад — возвращаемся к сетке дней текущей недели
    from datetime import timedelta as _td
    monday = d - _td(days=d.weekday())
    rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{monday.strftime('%Y-%m-%d')}")])
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    with contextlib.suppress(Exception):
        await message.bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=msg_id, reply_markup=kb)


async def _show_week_add_grid(message: types.Message, monday) -> None:
    """Показывает клавиатуру выбора дня недели (как в on_week_add) без текста недели."""
    from datetime import timedelta
    ru_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    ru_months_full = [
        "ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ",
        "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ",
    ]
    week_start = monday
    week_end = monday + timedelta(days=6)
    month_start = ru_months_full[week_start.month - 1]
    month_end = ru_months_full[week_end.month - 1]
    month_label = month_start if month_start == month_end else f"{month_start}-{month_end}"
    rows: list[list[types.InlineKeyboardButton]] = []
    rows.append([
        types.InlineKeyboardButton(text="⬅️", callback_data=f"week:prev:{week_start.strftime('%Y-%m-%d')}"),
        types.InlineKeyboardButton(text=month_label, callback_data="noop_month"),
        types.InlineKeyboardButton(text="➡️", callback_data=f"week:next:{week_start.strftime('%Y-%m-%d')}"),
    ])
    cur = week_start
    for _ in range(7):
        dow = ru_days[cur.weekday()]
        rows.append([
            types.InlineKeyboardButton(text=dow, callback_data=f"open_dow:{cur.strftime('%Y-%m-%d')}"),
            types.InlineKeyboardButton(text=str(cur.day), callback_data=f"open_day:{cur.strftime('%Y-%m-%d')}")
        ])
        cur = cur + timedelta(days=1)
    # Кнопка Назад — возвращаемся к сетке дней выбранной недели
    from datetime import timedelta as _td
    monday = week_start - _td(days=week_start.weekday())
    rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{monday.strftime('%Y-%m-%d')}")])
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer("\u2063", reply_markup=kb)



async def _show_week_schedule(message: types.Message, state: FSMContext, base_date=None, tg_id: int | None = None) -> None:
    from datetime import date, datetime, time, timedelta
    # Определяем базовую дату (понедельник нужной недели)
    today = base_date or date.today()
    start = today - timedelta(days=today.isoweekday() - 1)
    week_start = datetime.combine(start, time.min)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    target_id = tg_id if tg_id is not None else message.from_user.id
    extra = get_lessons_in_week(target_id, week_start, week_end)
    lines: list[str] = []
    cur = week_start
    ru_full = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    # Заголовок с месяцем(ами)
    ru_months_full = [
        "ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ",
        "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ",
    ]
    month_start = ru_months_full[week_start.month - 1]
    month_end = ru_months_full[week_end.month - 1]
    month_label = month_start if month_start == month_end else f"{month_start}-{month_end}"
    lines.append(month_label)
    lines.append("")
    for _ in range(7):
        label = f"{ru_full[cur.weekday()]}, {cur.strftime('%d.%m')}"
        lines.append(f"📅 {label}")
        day_events = sorted(extra.get(label, []), key=lambda e: e.get("start"))
        if not day_events:
            lines.append("  • —")
        else:
            for ev in day_events:
                s = ev.get("start")
                e = ev.get("end")
                t1 = s.strftime("%H:%M") if hasattr(s, 'strftime') else "--:--"
                t2 = e.strftime("%H:%M") if hasattr(e, 'strftime') else "--:--"
                title = ev.get("title") or "Занятие"
                lines.append(f"  • {t1}-{t2} — {title}")
        lines.append("")
        cur = cur + timedelta(days=1)
    # Теперь отправляем ОДНО сообщение с текстом недели и нижней панелью навигации
    # Кнопки: ⬅️  ➕ Добавить занятия  ➡️
    monday_str = start.strftime("%Y-%m-%d")
    rows: list[list[types.InlineKeyboardButton]] = [
        [
            types.InlineKeyboardButton(text="⬅️", callback_data=f"week:prev:{monday_str}"),
            types.InlineKeyboardButton(text="➡️", callback_data=f"week:next:{monday_str}"),
        ],
        [
            types.InlineKeyboardButton(text="➕ Добавить занятия", callback_data=f"week:add:{monday_str}"),
        ],
        [
            types.InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_main"),
        ],
    ]
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    msg = await message.answer("\n".join(lines).strip(), reply_markup=kb)
    try:
        await state.update_data(week_text_msg_id=msg.message_id, week_kb_msg_id=None)
    except Exception:
        pass


async def _refresh_week(message: types.Message, state: FSMContext, day: str) -> None:
    """Перестраивает недельный блок для недели, в которую входит day (YYYY-MM-DD)."""
    try:
        base_date = _dt.strptime(day, "%Y-%m-%d").date()
    except Exception:
        base_date = None
    # Почистим предыдущие сообщения недели
    try:
        data = await state.get_data()
        mid_kb = data.get("week_kb_msg_id")
        mid_text = data.get("week_text_msg_id")
        if mid_kb:
            with contextlib.suppress(Exception):
                await message.bot.delete_message(message.chat.id, int(mid_kb))
        if mid_text:
            with contextlib.suppress(Exception):
                await message.bot.delete_message(message.chat.id, int(mid_text))
    except Exception:
        pass
    await _show_week_schedule(message, state, base_date=base_date, tg_id=message.from_user.id)


@router.callback_query(lambda c: c.data and c.data.startswith("week:") and not c.data.startswith("week:add:"))
async def on_week_nav(cb: types.CallbackQuery, state: FSMContext):
    """Перелистывание недель вперёд/назад."""
    await cb.answer()
    try:
        _, direction, monday = cb.data.split(":", 2)
    except Exception:
        return
    from datetime import datetime, timedelta
    try:
        base = datetime.strptime(monday, "%Y-%m-%d").date()
    except Exception:
        return
    if direction == "prev":
        new_base = base - timedelta(days=7)
    elif direction == "next":
        new_base = base + timedelta(days=7)
    else:
        # другие подтипы (например, add) игнорируем
        return
    # Удалим прошлые сообщения (клавиатуру и текст недели) по сохранённым id
    try:
        data = await state.get_data()
        mid_kb = data.get("week_kb_msg_id")
        mid_text = data.get("week_text_msg_id")
        # Удалим сообщение, по которому нажали (на случай несовпадения id)
        with contextlib.suppress(Exception):
            await cb.message.delete()
        if mid_kb:
            with contextlib.suppress(Exception):
                await cb.bot.delete_message(cb.message.chat.id, int(mid_kb))
        if mid_text:
            with contextlib.suppress(Exception):
                await cb.bot.delete_message(cb.message.chat.id, int(mid_text))
        # На всякий случай удалим предыдущее сообщение относительно текущего
        with contextlib.suppress(Exception):
            await cb.bot.delete_message(cb.message.chat.id, cb.message.message_id - 1)
    except Exception:
        pass
    # Показать новую неделю и сохранить новые message_id
    # Передаём tg_id напрямую, иначе в callback message.from_user.id может быть id бота
    await _show_week_schedule(cb.message, state, base_date=new_base, tg_id=cb.from_user.id)


@router.callback_query(lambda c: c.data and c.data.startswith("week:add:"))
async def on_week_add(cb: types.CallbackQuery, state: FSMContext):
    """Открывает меню выбора дня недели (сетка как раньше)."""
    await cb.answer()
    from datetime import datetime, timedelta
    try:
        monday = datetime.strptime(cb.data.split(":", 2)[2], "%Y-%m-%d")
    except Exception:
        return
    ru_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    ru_months = [
        "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ", "ЯНВАРЬ", "ФЕВРАЛЬ",
        "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ", "ИЮЛЬ", "АВГУСТ",
    ]
    # Для заголовка месяца используем месяц начала и конца
    week_start = monday
    week_end = monday + timedelta(days=6)
    # Нормируем список месяцев (на случай перехода года)
    ru_months_full = [
        "ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ",
        "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ",
    ]
    month_start = ru_months_full[week_start.month - 1]
    month_end = ru_months_full[week_end.month - 1]
    month_label = month_start if month_start == month_end else f"{month_start}-{month_end}"

    rows: list[list[types.InlineKeyboardButton]] = []
    prev_monday = (week_start - timedelta(days=7)).strftime("%Y-%m-%d")
    next_monday = (week_start + timedelta(days=7)).strftime("%Y-%m-%d")
    rows.append([
        types.InlineKeyboardButton(text="⬅️", callback_data=f"week:prev:{week_start.strftime('%Y-%m-%d')}"),
        types.InlineKeyboardButton(text=month_label, callback_data="noop_month"),
        types.InlineKeyboardButton(text="➡️", callback_data=f"week:next:{week_start.strftime('%Y-%m-%d')}"),
    ])
    cur = week_start
    for _ in range(7):
        dow = ru_days[cur.weekday()]
        rows.append([
            types.InlineKeyboardButton(text=dow, callback_data=f"open_dow:{cur.strftime('%Y-%m-%d')}"),
            types.InlineKeyboardButton(text=str(cur.day), callback_data=f"open_day:{cur.strftime('%Y-%m-%d')}")
        ])
        cur = cur + timedelta(days=1)
    from datetime import timedelta
    monday = week_start - timedelta(days=week_start.weekday())
    rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{monday.strftime('%Y-%m-%d')}")])
    # Перед показом сетки — удалим верхнее сообщение дня, чтобы оставалось только одно окно с кнопками
    try:
        data = await state.get_data()
        day_msg_id = data.get("day_menu_msg_id")
        if day_msg_id:
            with contextlib.suppress(Exception):
                await cb.bot.delete_message(cb.message.chat.id, int(day_msg_id))
            await state.update_data(day_menu_msg_id=None, day_menu_day=None)
    except Exception:
        pass
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    # Покажем только клавиатуру (без текста)
    await cb.message.answer("\u2063", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("open_dow:"))
async def open_dow_menu(cb: types.CallbackQuery, state: FSMContext):
    """Открывает меню выбранного дня недели.
    Вместо списка дат показывает расписание этого дня (время и имя группы/ученика)
    и кнопку добавления занятий ДО следующего 30 мая.
    """
    await cb.answer()
    from datetime import datetime
    try:
        base_day = datetime.strptime(cb.data.split(":", 1)[1], "%Y-%m-%d")
    except Exception:
        return
    # Заголовок: название дня недели
    ru_days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    header = f"<b>{ru_days[base_day.weekday()]}</b> — расписание этого дня:" if 0 <= base_day.weekday() < 7 else "Расписание этого дня:"
    # Список текущих занятий на выбранную дату (каждое отдельным сообщением с кнопками)
    lines = [header]
    try:
        from services.lessons import list_lessons_by_day
        lessons = list_lessons_by_day(cb.from_user.id, day=base_day.strftime("%Y-%m-%d"))
    except Exception:
        lessons = []
    # Клавиатура: список занятий кнопками + управление
    rows: list[list[types.InlineKeyboardButton]] = []
    rows.append([types.InlineKeyboardButton(text="➕ Добавить занятия до 30 мая", callback_data=f"add_until_menu:{base_day.strftime('%Y-%m-%d')}")])
    if lessons:
        # Сортируем кнопки по времени начала
        def _tkey(v: str | None) -> int:
            try:
                s = (v or "").strip()
                hh, mm = s.split(":", 1)
                return int(hh) * 60 + int(mm)
            except Exception:
                return 24 * 60 + 1
        lessons = sorted(lessons, key=lambda l: _tkey(l.get('start')))
        for l in lessons:
            start = (l.get('start') or '').strip()
            end = (l.get('end') or '').strip()
            who_raw = (l.get("target") or "").strip()
            who = f"Группа {who_raw.lstrip('# ').strip()}" if l.get("kind") == "group" else (who_raw or "Ученик")
            label = f"{start}-{end} {who}"
            rows.append([types.InlineKeyboardButton(text=label, callback_data=f"open_lesson:{l.get('id')}")])
    # Кнопка Назад ведёт к сетке дней этой недели
    from datetime import timedelta
    monday = base_day - timedelta(days=base_day.weekday())
    rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{monday.strftime('%Y-%m-%d')}")])
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    text = "\n".join(lines)
    # Удалим недельный текстовый блок (оставим только верхнее окно) и временные сообщения
    try:
        data0 = await state.get_data()
        week_msg_id = data0.get("week_text_msg_id")
        if week_msg_id:
            with contextlib.suppress(Exception):
                await cb.bot.delete_message(cb.message.chat.id, int(week_msg_id))
            await state.update_data(week_text_msg_id=None)
    except Exception:
        pass
    await _clear_temp_msgs(cb.message, state)
    msg_id: int | None = None
    try:
        await cb.message.edit_text(text, parse_mode="HTML")
        await cb.message.edit_reply_markup(reply_markup=kb)
        msg_id = cb.message.message_id
    except Exception:
        sent = await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
        try:
            msg_id = sent.message_id
        except Exception:
            msg_id = None
    # Сохраним id сообщения и дату для последующего обновления при изменении времени
    try:
        await state.update_data(day_menu_msg_id=msg_id, day_menu_day=base_day.strftime("%Y-%m-%d"))
    except Exception:
        pass


@router.callback_query(lambda c: c.data and c.data.startswith("add_until_menu:"))
async def on_add_until_menu(cb: types.CallbackQuery, state: FSMContext):
    """Меню добавления занятий еженедельно ДО следующего 30 мая для выбранного дня недели."""
    await cb.answer()
    from datetime import datetime, timedelta, date
    try:
        base_day = datetime.strptime(cb.data.split(":", 1)[1], "%Y-%m-%d")
    except Exception:
        return
    d0: date = base_day.date()
    # Определяем ближайшее (следующее) 30 мая
    if (d0.month, d0.day) >= (5, 30):
        end_date = date(d0.year + 1, 5, 30)
    else:
        end_date = date(d0.year, 5, 30)
    # Формируем список дат с шагом 7 дней до end_date включительно
    days: list[str] = []
    cur = d0
    while cur <= end_date:
        days.append(cur.strftime("%Y-%m-%d"))
        cur = cur + timedelta(days=7)
    # Сохраним в состоянии
    await state.update_data(lesson_days=days, lesson_until_may30=True)
    rows = [
        [types.InlineKeyboardButton(text="➕ Группа (до 30 мая)", callback_data=f"add_lesson_group_until:{base_day.strftime('%Y-%m-%d')}")],
        [types.InlineKeyboardButton(text="➕ Ученик (до 30 мая)", callback_data=f"add_lesson_student_until:{base_day.strftime('%Y-%m-%d')}")],
        # Назад к сетке дней (простой шаг назад)
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{base_day.strftime('%Y-%m-%d')}")],
    ]
    await cb.message.answer("Что добавить до 30 мая?", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(lambda c: c.data and (c.data.startswith("add_lesson_student_until:") or c.data.startswith("add_lesson_group_until:")))
async def on_add_lesson_until(cb: types.CallbackQuery, state: FSMContext):
    """Подготовка к добавлению еженедельно до 30 мая (выбор ученика или ввод группы/времени)."""
    await cb.answer()
    data = cb.data
    kind = "student" if data.startswith("add_lesson_student_until:") else "group"
    try:
        day0 = data.split(":", 1)[1]
    except Exception:
        return
    await state.update_data(lesson_kind=kind)
    if kind == "student":
        students = get_all_students()
        kb = get_pick_students_for_day_kb(students, day=day0, page=1)
        await cb.message.answer("Выберите ученика (уроки будут созданы до 30 мая):", reply_markup=kb)
    else:
        await cb.message.answer("Введите время в формате HH:MM-HH:MM (например, 18:00-19:00):")
        await state.set_state(LessonStates.waiting_time)


@router.callback_query(lambda c: c.data and c.data.startswith("add8_menu:"))
async def on_add8_menu(cb: types.CallbackQuery, state: FSMContext):
    """Меню добавления занятий сразу на 8 недель для выбранного дня недели."""
    await cb.answer()
    from datetime import datetime, timedelta
    try:
        base_day = datetime.strptime(cb.data.split(":", 1)[1], "%Y-%m-%d")
    except Exception:
        return
    # Сформируем список из 8 дат
    days = [(base_day + timedelta(days=7 * i)).strftime("%Y-%m-%d") for i in range(8)]
    # Сохраним в состоянии
    await state.update_data(lesson_days=days)
    rows = [
        [types.InlineKeyboardButton(text="➕ Группа (8 недель)", callback_data=f"add_lesson_group8:{base_day.strftime('%Y-%m-%d')}")],
        [types.InlineKeyboardButton(text="➕ Ученик (8 недель)", callback_data=f"add_lesson_student8:{base_day.strftime('%Y-%m-%d')}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{base_day.strftime('%Y-%m-%d')}")],
    ]
    await cb.message.answer("Что добавить на ближайшие 8 недель?", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(lambda c: c.data and (c.data.startswith("add_lesson_student8:") or c.data.startswith("add_lesson_group8:")))
async def on_add_lesson8(cb: types.CallbackQuery, state: FSMContext):
    """Подготовка к добавлению на 8 недель (выбор ученика или ввод группы/времени)."""
    await cb.answer()
    data = cb.data
    kind = "student" if data.startswith("add_lesson_student8:") else "group"
    try:
        day0 = data.split(":", 1)[1]
    except Exception:
        return
    await state.update_data(lesson_kind=kind)
    if kind == "student":
        students = get_all_students()
        kb = get_pick_students_for_day_kb(students, day=day0, page=1)
        await cb.message.answer("Выберите ученика (уроки будут созданы на 8 недель):", reply_markup=kb)
    else:
        await cb.message.answer("Введите время в формате HH:MM-HH:MM (например, 18:00-19:00):")
        await state.set_state(LessonStates.waiting_time)


# ── Добавление уроков из инлайн-кнопок недели ──────────────────────────────────────────────────────────────────────

class LessonStates(StatesGroup):
    waiting_time = State()  # ждём строку времени HH:MM-HH:MM
    waiting_target = State()  # ждём @username или номер группы


@router.callback_query(lambda c: c.data and (c.data.startswith("add_lesson_student:") or c.data.startswith("add_lesson_group:")))
async def on_add_lesson(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    data = cb.data
    kind = "student" if data.startswith("add_lesson_student:") else "group"
    day = data.split(":", 1)[1]
    await state.update_data(lesson_day=day, lesson_kind=kind)
    if kind == "student":
        # покажем список учеников на выбор
        students = get_all_students()
        kb = get_pick_students_for_day_kb(students, day=day, page=1)
        await cb.message.answer("Выберите ученика:", reply_markup=kb)
        # временно запомним день и что ждём ученика
        await state.update_data(lesson_day=day, lesson_kind=kind)
        # состояние для клика по ученику нам не нужно (inline)
    else:
        await cb.message.answer(f"Введите время для {day} в формате HH:MM-HH:MM (например, 18:00-19:00):")
        await state.set_state(LessonStates.waiting_time)


@router.message(LessonStates.waiting_time)
async def on_lesson_time(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    import re

    def parse_range(raw: str) -> tuple[int, int, int, int] | None:
        # 1) HH:MM-HH:MM или с пробелами вокруг дефиса
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*[- ]\s*(\d{1,2}):(\d{2})\s*$", raw)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        # 2) HHMM-HHMM или HHMM HHMM
        m = re.match(r"^\s*(\d{3,4})\s*[- ]\s*(\d{3,4})\s*$", raw)
        if m:
            s, e = m.group(1), m.group(2)
            s_h = int(s[:-2])
            s_m = int(s[-2:])
            e_h = int(e[:-2])
            e_m = int(e[-2:])
            return s_h, s_m, e_h, e_m
        # 3) HH MM HH MM
        parts = [p for p in re.split(r"\s+", raw) if p]
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        return None

    parsed = parse_range(text)
    if not parsed:
        await message.answer("Не распознано. Допустимые форматы: HH:MM-HH:MM, HHMM-HHMM, HHMM HHMM, HH MM HH MM.")
        return
    h1, m1, h2, m2 = parsed
    text_norm = f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"
    await state.update_data(lesson_time=text_norm)
    data = await state.get_data()
    if (data.get("lesson_kind") == "student"):
        # Создаём запись сразу, используя выбранного ученика ранее
        day = data.get("lesson_day")
        user_id = data.get("lesson_student_id")
        # Попробуем найти username/label
        target = f"ID {user_id}"
        try:
            students = get_all_students()
            for s in students:
                if str(s.get("user_id")) == str(user_id):
                    uname = (s.get("username") or "").strip()
                    label = (s.get("label") or s.get("full_name") or "").strip()
                    if uname:
                        target = f"@{uname}" if not uname.startswith("@") else uname
                    elif label:
                        target = label
                    break
        except Exception:
            pass
        start_s, end_s = text_norm.split("-", 1)
        # Поддержка добавления на 8 недель, если заранее выбран режим 8 недель
        days8 = data.get("lesson_days")
        if days8:
            for d in list(days8):
                add_lesson(message.from_user.id, day=d, start=start_s, end=end_s, kind="student", target=target)
        else:
            add_lesson(message.from_user.id, day=day, start=start_s, end=end_s, kind="student", target=target)
        # Уведомим ученика в govr-боте
        try:
            uid_int = int(user_id)
        except Exception:
            uid_int = None
        if uid_int:
            notify_text = f"Вам назначено занятие {day} {start_s}-{end_s}."
            try:
                await send_message_to_user_via_govr(uid_int, notify_text)
            except Exception:
                pass
        # Автообновление недельного отображения (по первой дате)
        await _refresh_week(message, state, day)
        until = bool(data.get("lesson_until_may30"))
        await message.answer("✅ Уроки до 30 мая добавлены." if until and days8 else "✅ Урок(и) добавлен(ы).")
        await state.set_state(None)
        return
    else:
        await message.answer("Для какой группы урок? Отправьте номер группы (например, 101):")
        await state.set_state(LessonStates.waiting_target)


@router.message(LessonStates.waiting_target)
async def on_lesson_target(message: types.Message, state: FSMContext):
    target = (message.text or "").strip()
    data = await state.get_data()
    day = data.get("lesson_day")
    kind = data.get("lesson_kind")
    time_str = data.get("lesson_time")
    try:
        start, end = [t.strip() for t in time_str.split("-", 1)]
    except Exception:
        await message.answer("Ошибка времени. Начните заново: нажмите кнопку добавления ещё раз.")
        await state.set_state(None)
        return

    # Простая валидация цели
    if kind == "student" and not target.startswith("@"):
        await message.answer("Для ученика отправьте @username (например, @ivan). Попробуйте ещё раз:")
        return
    if kind == "group":
        target = target.lstrip("# ")

    # Если добавление на несколько недель — создадим записи по сохранённым дням
    days8 = data.get("lesson_days")
    if days8:
        for d in list(days8):
            add_lesson(message.from_user.id, day=d, start=start, end=end, kind=kind, target=target)
        first_day = days8[0]
        await _refresh_week(message, state, first_day)
        until = bool(data.get("lesson_until_may30"))
        await message.answer("✅ Уроки до 30 мая добавлены." if until else "✅ Уроки на 8 недель добавлены.")
    else:
        add_lesson(message.from_user.id, day=day, start=start, end=end, kind=kind, target=target)
        # Автообновим недельный вид на соответствующей неделе
        await _refresh_week(message, state, day)
        await message.answer("✅ Урок добавлен.")
    await state.set_state(None)


@router.callback_query(lambda c: c.data and (c.data.startswith("pick_lesson_student:") or c.data.startswith("pick_lesson_student_page:")))
async def on_pick_student(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    if cb.data.startswith("pick_lesson_student_page:"):
        try:
            _, day, page = cb.data.split(":", 2)
            page = int(page)
        except Exception:
            return
        students = get_all_students()
        kb = get_pick_students_for_day_kb(students, day=day, page=page)
        try:
            await cb.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            await cb.message.answer("Выберите ученика:", reply_markup=kb)
        return

    # Выбор конкретного ученика
    try:
        _, day, user_id = cb.data.split(":", 2)
    except Exception:
        return
    await state.update_data(lesson_day=day, lesson_kind="student", lesson_student_id=user_id)
    await cb.message.answer(f"Введите время для {day} в формате HH:MM-HH:MM (например, 18:00-19:00):")
    await state.set_state(LessonStates.waiting_time)


# ── Прокси-обработчики главного меню (в этом же роутере, чтобы перехватывать раньше state-хендлеров) ─────────

@router.message(StateFilter('*'), lambda m: m.text and "ученики онлайн" in m.text.lower())
async def proxy_online(message: types.Message, state: FSMContext):
    """Перенаправляет в раздел онлайн, очищая текущее состояние."""
    try:
        await state.clear()
    except Exception:
        pass
    try:
        from handlers import online as online_handlers  # импорт внутри, чтобы не ловить циклические зависимости при загрузке
        await online_handlers.online_entry(message, state)
    except Exception:
        # Если что-то пошло не так — просто молча игнорируем
        return


@router.message(StateFilter('*'), lambda m: m.text == "📈 Успеваемость")
async def proxy_report(message: types.Message, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass
    try:
        from handlers import report as report_handlers
        await report_handlers.report_entry(message, state)
    except Exception:
        return


@router.message(StateFilter('*'), lambda m: m.text == "🛠 Управление заданиями")
async def proxy_tasks(message: types.Message, state: FSMContext):
    try:
        await state.clear()
    except Exception:
        pass
    try:
        from handlers import add_task as add_task_handlers
        await add_task_handlers.manage_tasks_menu(message, state)
    except Exception:
        return


@router.message(StateFilter('*'), lambda m: m.text == "👥 Добавить ученика")
async def show_students_list(message: types.Message, state: FSMContext):
    """Показывает список всех зарегистрированных учеников"""
    await state.clear()
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    students = get_all_students_with_plans()
    
    if not students:
        await message.answer("Пока нет зарегистрированных учеников.")
        return
    
    # Добавляем информацию о том, кто уже в группе
    for student in students:
        student["is_in_group"] = is_student_in_group(student["user_id"])

    # Сохраняем исходный список в FSM (для фильтров/поиска)
    await state.update_data(
        students=students,
        only_not_in_group=False,
        search_query="",
    )

    keyboard = get_students_keyboard(students, page=1, page_size=30, show_plans=True, has_search=False, only_not_in_group=False)
    sent = await message.answer(
        "Список всех зарегистрированных учеников:\n\n"
        "Нажмите на ученика, чтобы добавить его в группу для доступа к тарифу 'Групповые':",
        reply_markup=keyboard
    )
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(StateFilter('*'), lambda m: m.text == "✅ Ученики в группе")
async def show_group_students(message: types.Message, state: FSMContext):
    """Показывает список только тех учеников, кто уже в группе"""
    await state.clear()
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    students = get_all_students_with_plans()

    # Отметим статус и отфильтруем
    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])
    students = [s for s in students if s.get("is_in_group")]

    if not students:
        await message.answer("Пока в группе никого нет.")
        return

    await state.update_data(
        students=students,
        only_not_in_group=False,
        search_query="",
    )

    keyboard = get_students_keyboard(
        students, page=1, page_size=30,
        show_plans=True,
        has_search=False,
        only_not_in_group=False,
        show_controls=True,
        show_only_not_in_group_toggle=False,
    )
    sent = await message.answer(
        "Ученики, которые уже в группе. Листайте страницы ⬅️➡️ или используйте поиск.",
        reply_markup=keyboard,
    )
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(StateFilter('*'), lambda m: m.text == "📚 Управление группами")
async def manage_groups_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    sent = await message.answer("Выберите действие:", reply_markup=get_manage_groups_keyboard())
    message_manager.add_message(message.from_user.id, sent.message_id)


@router.callback_query(lambda c: c.data == "manage_groups_back")
async def manage_groups_back(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите действие:", reply_markup=get_manage_groups_keyboard())


@router.callback_query(lambda c: c.data == "wg_broadcast_start")
async def wg_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    groups = get_all_group_numbers()
    if not groups:
        await callback.message.answer("Группы пока не созданы. Сначала добавьте участников.")
        return
    # Покажем кнопки выбора группы
    try:
        await callback.message.edit_text("Выберите группу для отправки сообщения:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_broadcast_group"))
    except Exception:
        await callback.message.answer("Выберите группу для отправки сообщения:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_broadcast_group"))
    # Оставим старый способ ввода числа как резервный
    await state.set_state(WorkGroups.waiting_broadcast_group)


@router.message(WorkGroups.waiting_broadcast_group)
async def wg_broadcast_group(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        group_no = int(text)
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 101). Попробуйте ещё раз:")
        return
    await state.update_data(broadcast_group=group_no)
    await message.answer("Введите текст сообщения, оно уйдёт всем участникам группы:")
    await state.set_state(WorkGroups.waiting_broadcast_text)


@router.callback_query(lambda c: c.data.startswith("pick_broadcast_group:"))
async def pick_broadcast_group(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("wg_remove:"))
async def remove_from_teacher_group(cb: types.CallbackQuery, state: FSMContext):
    """Удаляет ученика из общей группы преподавателя (teacher_groups) и обновляет текущую страницу списка."""
    try:
        parts = cb.data.split(":")
        user_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 1
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return
    from services.groups import remove_student_from_group
    remove_student_from_group(user_id)

    # Обновим текущую страницу
    data = await state.get_data()
    students = data.get("students") or get_all_students_with_plans()
    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])
    only_not_in_group = bool((await state.get_data()).get("only_not_in_group"))
    search_query = (await state.get_data()).get("search_query") or ""
    filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=search_query)
    keyboard = get_students_keyboard(
        filtered, page=page, page_size=30,
        show_plans=True,
        has_search=bool(search_query.strip()),
        only_not_in_group=only_not_in_group,
    )
    try:
        await cb.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        await cb.answer("Удалён из группы")


@router.callback_query(lambda c: c.data and c.data.startswith("wg_wremove:"))
async def remove_from_work_group(cb: types.CallbackQuery):
    """Исключает ученика из рабочей группы по номеру."""
    try:
        _, group_no, user_id = cb.data.split(":", 2)
        group_no = int(group_no)
        user_id = int(user_id)
    except Exception:
        await cb.answer("Не понимаю", show_alert=True)
        return
    remove_user_from_work_group(group_no, user_id)
    # Обновим список участников этой группы в текущем сообщении
    user_ids = get_work_group_members(group_no)
    students = get_all_students_with_plans()
    by_id = {s["user_id"]: s for s in students}
    members = [by_id.get(uid, {"user_id": uid, "label": f"ID {uid}"}) for uid in user_ids]
    try:
        await cb.message.edit_text(f"Участники группы {group_no}:", reply_markup=get_group_members_keyboard(members, group_no=group_no))
    except Exception:
        await cb.message.answer(f"Участники группы {group_no}:", reply_markup=get_group_members_keyboard(members, group_no=group_no))
    await cb.answer("Исключён из рабочей группы")


@router.message(WorkGroups.waiting_broadcast_text)
async def wg_broadcast_text(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст пуст. Отправьте текст сообщения:")
        return
    data = await state.get_data()
    group_no = int(data.get("broadcast_group") or 0)
    user_ids = get_work_group_members(group_no)
    if not user_ids:
        await message.answer(f"В группе {group_no} нет участников.")
        await state.set_state(None)
        return
    ok, fail = await broadcast_message_to_group_via_govr(group_no, text)
    await message.answer(f"Отправлено: {ok}. Ошибок: {fail}.")
    await state.set_state(None)


@router.callback_query(lambda c: c.data and c.data.startswith("open_day:"))
async def on_open_day(cb: types.CallbackQuery, state: FSMContext):
    """Открывает карточку дня: показывает дату, существующие занятия и кнопку Добавить."""
    await cb.answer()
    day = cb.data.split(":", 1)[1]
    # Список уже назначенных уроков этого преподавателя
    from services.lessons import list_lessons_by_day
    lessons = list_lessons_by_day(cb.from_user.id, day=day)
    # Текст заголовка
    from datetime import datetime, date
    d = datetime.strptime(day, "%Y-%m-%d")
    header = d.strftime("%A, %d %B").capitalize()
    lines = [f"<b>{header}</b>"]

    # Наши локальные уроки
    for l in lessons:
        who = (l.get("target") or "").strip()
        if l.get("kind") == "group":
            title = f"Группа {who}"
        else:
            title = who or "Ученик"
        lines.append(f"• {l.get('start')}-{l.get('end')} — {title}")
    if len(lines) == 1:
        lines.append("— занятий нет")
    # Клавиатура: на каждое занятие — кнопка; плюс Добавить
    rows: list[list[types.InlineKeyboardButton]] = []
    # Кнопки для локальных уроков
    for l in lessons:
        label = f"{l.get('start')}-{l.get('end')} • {'Гр' if l.get('kind')=='group' else 'Уч'}"
        rows.append([types.InlineKeyboardButton(text=label, callback_data=f"open_lesson:{l.get('id')}")])
    rows.append([types.InlineKeyboardButton(text="➕ Добавить занятие", callback_data=f"add_menu:{day}")])
    # Кнопка Назад — возвращаемся к сетке дней этой недели
    from datetime import timedelta
    monday = d - timedelta(days=d.weekday())
    rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{monday.strftime('%Y-%m-%d')}")])
    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    await cb.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("open_lesson:"))
async def on_open_lesson(cb: types.CallbackQuery, state: FSMContext):
    """Меню действий по занятию: изменить время, написать группе, отменить/удалить."""
    await cb.answer()
    try:
        lesson_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    # Построим клавиатуру действий
    rows = [
        [types.InlineKeyboardButton(text="⏱ Изменить время", callback_data=f"lesson_change_time:{lesson_id}")],
        [types.InlineKeyboardButton(text="🔔 Уведомление", callback_data=f"lesson_notify_setup:{lesson_id}")],
        [types.InlineKeyboardButton(text="🛑 Отменить занятие", callback_data=f"lesson_cancel:{lesson_id}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_day_menu")],
    ]
    sent = await cb.message.answer("Выберите действие:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows))
    # Запомним как временное сообщение для автоочистки
    with contextlib.suppress(Exception):
        await _add_temp_msg(state, sent.message_id)
@router.callback_query(lambda c: c.data and c.data.startswith("lesson_notify_setup:"))
async def on_lesson_notify_setup(cb: types.CallbackQuery, state: FSMContext):
    """Запрашивает у преподавателя количество минут до занятия для уведомления."""
    await cb.answer()
    try:
        lesson_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    await state.update_data(notify_lesson_id=lesson_id)
    # Оставляем экран чистым: отправим короткую подсказку без лишних сообщений
    sent = await cb.message.answer("За сколько минут до занятия присылать уведомление? (например, 30 или 60)")
    with contextlib.suppress(Exception):
        await _add_temp_msg(state, sent.message_id)
    await state.set_state(ScheduleStates.waiting_notify_minutes)


@router.message(ScheduleStates.waiting_notify_minutes)
async def on_notify_minutes_input(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        minutes = int(text)
    except Exception:
        await message.answer("Введите целое число минут, например 30 или 60")
        return
    if minutes < 0:
        minutes = 0
    data = await state.get_data()
    lesson_id = int(data.get("notify_lesson_id") or 0)
    if not lesson_id:
        await message.answer("Не удалось определить занятие.")
        await state.set_state(None)
        return
    # Сохраняем настройку
    try:
        from services.lessons import update_lesson_notify_minutes, get_lesson_by_id
        ok = update_lesson_notify_minutes(lesson_id, minutes)
        lesson = get_lesson_by_id(lesson_id)
        day_for_refresh = str(lesson.get("day")) if lesson and lesson.get("day") else None
    except Exception:
        ok = False
        day_for_refresh = None
    # Эфемерно подтвердим и почистим
    try:
        sent = await message.answer("Готово." if ok else "Не удалось сохранить.")
        await _add_temp_msg(state, sent.message_id)
    except Exception:
        pass
    # Обновим UI недели и список занятий дня
    if day_for_refresh:
        with contextlib.suppress(Exception):
            await _refresh_week(message, state, day_for_refresh)
    try:
        data = await state.get_data()
        day_menu_msg_id = data.get("day_menu_msg_id")
        day_menu_day = data.get("day_menu_day")
        if day_menu_msg_id and day_menu_day:
            await _rebuild_day_menu(message, int(day_menu_msg_id), str(day_menu_day))
    except Exception:
        pass
    await _clear_temp_msgs(message, state)
    await _focus_day_menu_only(message, state)
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "back_to_day_menu")
async def back_to_day_menu(cb: types.CallbackQuery, state: FSMContext):
    """Возврат к верхнему сообщению дня: удаляем все вспомогательные сообщения
    (меню действий, подсказки), оставляя только заголовок дня с кнопками."""
    await cb.answer()
    # Просто закрываем меню действий
    with contextlib.suppress(Exception):
        await cb.message.delete()


@router.callback_query(lambda c: c.data and c.data.startswith("lesson_change_time:"))
async def on_lesson_change_time(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        lesson_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    await state.update_data(change_lesson_id=lesson_id)
    sent = await cb.message.answer("Введите время в формате HH:MM-HH:MM:")
    with contextlib.suppress(Exception):
        await _add_temp_msg(state, sent.message_id)
    await state.set_state(ScheduleStates.waiting_change_time)


@router.message(ScheduleStates.waiting_change_time)
async def change_time_input(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    import re

    def parse_range(raw: str) -> tuple[int, int, int, int] | None:
        # 1) HH:MM-HH:MM или с пробелами вокруг дефиса
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*[- ]\s*(\d{1,2}):(\d{2})\s*$", raw)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        # 2) HHMM-HHMM или HHMM HHMM
        m = re.match(r"^\s*(\d{3,4})\s*[- ]\s*(\d{3,4})\s*$", raw)
        if m:
            s, e = m.group(1), m.group(2)
            s_h = int(s[:-2])
            s_m = int(s[-2:])
            e_h = int(e[:-2])
            e_m = int(e[-2:])
            return s_h, s_m, e_h, e_m
        # 3) HH MM HH MM
        parts = [p for p in re.split(r"\s+", raw) if p]
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        return None

    parsed = parse_range(text)
    if not parsed:
        await message.answer("Форматы: HH:MM-HH:MM, HHMM-HHMM, HHMM HHMM, HH MM HH MM")
        return
    data = await state.get_data()
    lesson_id = int(data.get("change_lesson_id") or 0)
    from services.lessons import update_lesson_time
    h1, m1, h2, m2 = parsed
    ok = update_lesson_time(lesson_id, start=f"{h1:02d}:{m1:02d}", end=f"{h2:02d}:{m2:02d}")
    # Короткое подтверждение и очистка, чтобы не засорять экран
    # Не оставляем подтверждение — просто тихо обновляем UI
    # Попробуем обновить список кнопок в меню дня (верхнее сообщение) и недельный блок
    try:
        from services.lessons import get_lesson_by_id
        lesson = get_lesson_by_id(lesson_id)
    except Exception:
        lesson = None
    # Обновим верхний недельный блок (если знаем день)
    day_for_refresh = None
    if lesson and (lesson.get("day")):
        day_for_refresh = str(lesson.get("day"))
    if day_for_refresh:
        with contextlib.suppress(Exception):
            await _refresh_week(message, state, day_for_refresh)
    # Обновим клавиатуру списка занятий в сообщении дня
    try:
        data = await state.get_data()
        day_menu_msg_id = data.get("day_menu_msg_id")
        day_menu_day = data.get("day_menu_day")
        if day_menu_msg_id and day_menu_day:
            await _rebuild_day_menu(message, int(day_menu_msg_id), str(day_menu_day))
    except Exception:
        pass
    # Очистим подсказки и сфокусируем экран на сообщении дня
    await _clear_temp_msgs(message, state)
    await _focus_day_menu_only(message, state)
    await state.set_state(None)


@router.callback_query(lambda c: c.data and c.data.startswith("lesson_delete:"))
async def on_lesson_delete(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        lesson_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    from services.lessons import delete_lesson, get_lesson_by_id
    lesson = get_lesson_by_id(lesson_id)
    ok = delete_lesson(lesson_id)
    # Если это личное занятие — уведомим ученика
    if ok and lesson and (lesson.get("kind") == "student"):
        start = lesson.get("start") or ""
        end = lesson.get("end") or ""
        day = lesson.get("day") or ""
        uid = resolve_user_id_from_target(lesson.get("target") or "")
        if uid:
            text = f"Ваше занятие {day} {start}-{end} удалено."
            try:
                await send_message_to_user_via_govr(int(uid), text)
            except Exception:
                pass
    # Эфемерное подтверждение
    try:
        sent = await cb.message.answer("Удалено." if ok else "Не удалось удалить.")
        await _add_temp_msg(state, sent.message_id)
    except Exception:
        pass
    await _clear_temp_msgs(cb.message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("lesson_cancel:"))
async def on_lesson_cancel(cb: types.CallbackQuery, state: FSMContext):
    """Отменяет занятие: отправляет уведомление и УДАЛЯЕТ запись из расписания.
    Это объединяет прежние действия «Отменить» и «Удалить»."""
    await cb.answer()
    try:
        lesson_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    from services.lessons import delete_lesson, get_lesson_by_id
    lesson = get_lesson_by_id(lesson_id)
    ok = delete_lesson(lesson_id)
    if ok and lesson and (lesson.get("kind") == "group"):
        # Попробуем разослать уведомление участникам группы
        try:
            group_no = int((lesson.get("target") or "").lstrip("# ").strip())
        except Exception:
            group_no = 0
        if group_no:
            from services.groups import broadcast_message_to_group_via_govr
            start = lesson.get("start") or ""
            end = lesson.get("end") or ""
            day = lesson.get("day") or ""
            text = f"Внимание! Занятие группы {group_no} {day} {start}-{end} отменено."
            try:
                await broadcast_message_to_group_via_govr(group_no, text)
            except Exception:
                pass
    # Уведомление ученику для личного занятия
    if ok and lesson and (lesson.get("kind") == "student"):
        start = lesson.get("start") or ""
        end = lesson.get("end") or ""
        day = lesson.get("day") or ""
        uid = resolve_user_id_from_target(lesson.get("target") or "")
        if uid:
            text = f"Занятие {day} {start}-{end} отменено."
            try:
                await send_message_to_user_via_govr(int(uid), text)
            except Exception:
                pass
    # Эфемерное подтверждение
    try:
        sent = await cb.message.answer("Занятие отменено и удалено." if ok else "Не удалось отменить.")
        await _add_temp_msg(state, sent.message_id)
    except Exception:
        pass
    await _clear_temp_msgs(cb.message, state)


@router.callback_query(lambda c: c.data and c.data.startswith("lesson_broadcast:"))
async def on_lesson_broadcast(cb: types.CallbackQuery, state: FSMContext):
    """Старая ветка рассылки — больше не используется в меню, оставляем на всякий случай."""
    await cb.answer()
    try:
        lesson_id = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    from services.lessons import get_lesson_by_id
    lesson = get_lesson_by_id(lesson_id)
    if not lesson or (lesson.get("kind") != "group"):
        await cb.message.answer("Это не групповое занятие или запись не найдена.")
        return
    # Извлечём номер группы из target
    group_str = (lesson.get("target") or "").lstrip("# ").strip()
    try:
        group_no = int(group_str)
    except Exception:
        await cb.message.answer("Не удалось определить номер группы.")
        return
    # Подставим и переключим state на ввод текста
    await state.update_data(broadcast_group=group_no)
    await cb.message.answer(f"Группа {group_no} выбрана. Введите текст сообщения:")
    await state.set_state(WorkGroups.waiting_broadcast_text)

# Удалено: iCal просмотр (open_ics)


@router.callback_query(lambda c: c.data and c.data.startswith("add_menu:"))
async def on_add_menu(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    day = cb.data.split(":", 1)[1]
    rows = [
        [types.InlineKeyboardButton(text="➕ Группа", callback_data=f"add_lesson_group:{day}")],
        [types.InlineKeyboardButton(text="➕ Ученик", callback_data=f"add_lesson_student:{day}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"week:add:{day}")],
    ]
    await cb.message.answer("Что добавить?", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(lambda c: c.data == "day_back")
async def day_back(cb: types.CallbackQuery, state: FSMContext):
    """Удаляет все сообщения вниз до сообщения с кнопками недели (оставляем клавиатуру недели)."""
    await cb.answer()
    # Удалим верхнее сообщение дня, чтобы оставить только недельное окно
    try:
        data0 = await state.get_data()
        day_msg_id = data0.get("day_menu_msg_id")
        if day_msg_id:
            with contextlib.suppress(Exception):
                await cb.bot.delete_message(cb.message.chat.id, int(day_msg_id))
            await state.update_data(day_menu_msg_id=None, day_menu_day=None)
    except Exception:
        pass
    try:
        data = await state.get_data()
        kb_id_raw = data.get("week_kb_msg_id")
        text_id_raw = data.get("week_text_msg_id")
        kb_id = int(kb_id_raw) if kb_id_raw else None
        text_id = int(text_id_raw) if text_id_raw else None
    except Exception:
        kb_id = None
        text_id = None
    chat_id = cb.message.chat.id
    cur_id = cb.message.message_id
    # Целимся остановиться ПЕРЕД недельным текстом, чтобы его не удалять.
    # Если text_id неизвестен — останавливаемся перед клавиатурой.
    stop_before_id = (text_id + 1) if (text_id and cur_id > text_id) else ((kb_id + 1) if kb_id else None)
    if stop_before_id and cur_id >= stop_before_id:
        # Удаляем все сообщения от текущего вниз до stop_before_id (не включая stop_before_id)
        for mid in range(cur_id, stop_before_id - 1, -1):
            with contextlib.suppress(Exception):
                await cb.bot.delete_message(chat_id, mid)
    else:
        # Если kb_id неизвестен — просто удалим текущее сообщение
        with contextlib.suppress(Exception):
            await cb.message.delete()


## Удалено: iCal клонирование событий

@router.callback_query(lambda c: c.data == "wg_add_start")
async def wg_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    # Покажем список существующих групп, если есть
    groups = get_all_group_numbers()
    if groups:
        try:
            await callback.message.edit_text("Существующие группы:", reply_markup=get_group_numbers_keyboard(groups))
        except Exception:
            await callback.message.answer("Существующие группы:", reply_markup=get_group_numbers_keyboard(groups))
    # Предложим выбрать группу кнопками для добавления ученика
    try:
        await callback.message.answer("Выберите группу, куда добавить ученика:", reply_markup=get_group_pick_keyboard(groups or [], prefix="pick_add_group"))
    except Exception:
        pass
    await state.set_state(WorkGroups.waiting_group_number)


@router.message(WorkGroups.waiting_group_number)
async def wg_input_group(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        group_no = int(text)
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 101). Попробуйте ещё раз:")
        return
    await state.update_data(group_no=group_no)
    await message.answer("Теперь отправьте username ученика с @ (например, @ivan_ivanov):")
    await state.set_state(WorkGroups.waiting_username)


@router.callback_query(lambda c: c.data.startswith("pick_add_group:"))
async def pick_add_group(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_task_results:"))
async def wg_task_results(cb: types.CallbackQuery):
    """Показывает итоги по набору: по каждому ученику группы — верных/всего и %."""
    try:
        task_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return

    info = compute_group_task_results(task_id)
    group_no = info.get('group_no')
    title = info.get('title') or f"Набор {task_id}"
    qids = info.get('qids') or []
    results = info.get('results') or []

    if group_no is None:
        await cb.answer("Набор не найден", show_alert=True)
        return

    lines: list[str] = []
    lines.append(f"📊 Результаты набора «{title}» (группа {group_no})")
    lines.append(f"Всего вопросов в наборе: {len(qids)}")
    lines.append("")

    if not results:
        lines.append("Пока нет участников группы или ответов по этому набору.")
    else:
        lines.append("<b>Ученик — верных/всего (точность)</b>")
        for r in results:
            label = str(r.get('label') or f"ID {r.get('user_id')}")
            if len(label) > 30:
                label = label[:27] + "…"
            lines.append(f"{label} — {r['correct']}/{r['total']} ({r['pct']}%)")

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"wg_tasks_list:{group_no}")]]
    )
    text = "\n".join(lines)
    try:
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.message(WorkGroups.waiting_username)
async def wg_input_username(message: types.Message, state: FSMContext):
    username = (message.text or "").strip()
    if not username:
        await message.answer("Username не распознан. Отправьте в формате @username:")
        return
    data = await state.get_data()
    group_no = int(data.get("group_no") or 0)

    user_id = find_user_id_by_username(username)
    if not user_id:
        await message.answer("Не нашли такого пользователя в базе. Попросите его написать боту, затем повторите.")
        await state.set_state(None)
        return

    add_user_to_work_group(group_no, user_id)
    await message.answer(f"✅ Пользователь {username} (id={user_id}) добавлен в рабочую группу {group_no}.")
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "manage_groups_list")
async def manage_groups_list(callback: types.CallbackQuery):
    await callback.answer()
    groups = get_all_group_numbers()
    if not groups:
        await callback.message.edit_text("Группы пока не созданы. Нажмите '➕ Добрать в рабочие группы' чтобы начать.", reply_markup=get_manage_groups_keyboard())
        return
    try:
        await callback.message.edit_text("Список групп:", reply_markup=get_group_numbers_keyboard(groups))
    except Exception:
        await callback.message.answer("Список групп:", reply_markup=get_group_numbers_keyboard(groups))


@router.callback_query(lambda c: c.data.startswith("wg_open:"))
async def wg_open_group(callback: types.CallbackQuery):
    await callback.answer()
    try:
        group_no = int(callback.data.split(":")[1])
    except Exception:
        group_no = 0
    user_ids = get_work_group_members(group_no)
    if not user_ids:
        await callback.message.edit_text(f"В группе {group_no} пока нет участников.", reply_markup=get_manage_groups_keyboard())
        return
    # Обогатим данными (label)
    students = get_all_students_with_plans()
    by_id = {s["user_id"]: s for s in students}
    members = [by_id.get(uid, {"user_id": uid, "label": f"ID {uid}"}) for uid in user_ids]
    try:
        await callback.message.edit_text(f"Участники группы {group_no}:", reply_markup=get_group_members_keyboard(members, group_no=group_no))
    except Exception:
        await callback.message.answer(f"Участники группы {group_no}:", reply_markup=get_group_members_keyboard(members, group_no=group_no))


@router.callback_query(lambda c: c.data == "wg_tasks_start")
async def wg_tasks_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    groups = get_all_group_numbers()
    if not groups:
        await callback.message.answer("Группы пока не созданы. Сначала добавьте участников.")
        return
    try:
        await callback.message.edit_text("Выберите группу, для которой создаём задания:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_tasks_group"))
    except Exception:
        await callback.message.answer("Выберите группу, для которой создаём задания:", reply_markup=get_group_pick_keyboard(groups, prefix="pick_tasks_group"))
    await state.set_state(WorkGroups.waiting_tasks_group)


@router.message(WorkGroups.waiting_tasks_group)
async def wg_tasks_group(message: types.Message, state: FSMContext):
    try:
        group_no = int((message.text or "").strip())
    except ValueError:
        await message.answer("Пожалуйста, введите целое число (например, 1). Попробуйте ещё раз:")
        return
    await state.update_data(tasks_group=group_no)
    tasks = list_group_tasks(group_no)
    if tasks:
        try:
            await message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
        except Exception:
            # На случай, если редактирование/отправка с клавиатурой не удалось — покажем текстом и следом клавиатуру
            await message.answer("У этой группы уже есть наборы:")
            await message.answer("Выберите набор:", reply_markup=get_group_tasks_kb(tasks))
    await message.answer("Введите название набора (например, Домашка 24.09):")
    await state.set_state(WorkGroups.waiting_tasks_title)


@router.callback_query(lambda c: c.data.startswith("pick_tasks_group:"))
async def pick_tasks_group(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        group_no = int(cb.data.split(":", 1)[1])
    except Exception:
        return
    await state.update_data(tasks_group=group_no)
    # Показать уже имеющиеся наборы
    tasks = list_group_tasks(group_no)
    if tasks:
        try:
            await _safe_edit_text(cb.message, "У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
        except Exception:
            await cb.message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    await cb.message.answer("Введите название набора (например, Домашка 24.09):")
    await state.set_state(WorkGroups.waiting_tasks_title)


@router.message(WorkGroups.waiting_tasks_title)
async def wg_tasks_title(message: types.Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не распознано, введите ещё раз:")
        return
    await state.update_data(tasks_title=title)
    await message.answer("Выберите базу:", reply_markup=get_exam_pick_keyboard())
    await state.set_state(WorkGroups.waiting_tasks_exam)


@router.message(WorkGroups.waiting_tasks_exam)
async def wg_tasks_exam(message: types.Message, state: FSMContext):
    # Если пользователь всё же напишет текстом, поддержим старый способ
    exam = (message.text or "").strip().lower()
    if exam in {"ege", "егэ", "oge", "огэ"}:
        canonical = "ege" if exam in {"ege", "егэ"} else "oge"
        await state.update_data(tasks_exam=canonical)
        await message.answer("Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(canonical))
        await state.set_state(WorkGroups.waiting_tasks_ids)
    else:
        await message.answer("Выберите базу:", reply_markup=get_exam_pick_keyboard())


@router.message(WorkGroups.waiting_tasks_ids)
async def wg_tasks_ids(message: types.Message, state: FSMContext):
    ids_text = (message.text or "").strip()
    if not ids_text:
        await message.answer("Пустой ввод. Примеры: 1, 5, 10  |  variant: test.pdf  |  types: 1=5, 2=3")
        return
    data = await state.get_data()
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or "Набор"
    exam = (data.get("tasks_exam") or "ege").lower()

    text_low = ids_text.lower()
    ids: list[int] = []

    # 1) Вариант по имени файла
    if text_low.startswith(("variant:", "вариант:", "filename:", "file:", "файл:")):
        filename = ids_text.split(":", 1)[1].strip() if ":" in ids_text else ""
        ids = get_question_ids_by_filename(exam, filename)
        if not ids:
            await message.answer("Не нашёл вопросы по такому имени файла. Проверьте 'variant: <filename>' и попробуйте снова.")
            return

    # 2) По типам и количеству
    elif text_low.startswith(("types:", "type:", "типы:", "виды:")):
        body = ids_text.split(":", 1)[1] if ":" in ids_text else ""
        pairs = [p for p in re.split(r"[;,]", body) if p.strip()]
        if not pairs:
            await message.answer("Не распознал пары типов. Пример: types: 1=5, 2=3")
            return
        max_type = 28 if exam == "ege" else 19
        collected: list[int] = []
        for pair in pairs:
            m = re.match(r"\s*(\d+)\s*[:=x×]\s*(\d+)\s*", pair)
            if not m:
                await message.answer("Неверный формат. Используйте: 1=5, 2=3")
                return
            t = int(m.group(1))
            cnt = int(m.group(2))
            if t < 1 or t > max_type or cnt < 1:
                await message.answer(f"Тип должен быть 1..{max_type}, количество > 0")
                return
            collected.extend(get_question_ids_by_type(exam, t, cnt))
        seen = set()
        ids = [x for x in collected if not (x in seen or seen.add(x))]
        if not ids:
            await message.answer("Не удалось подобрать вопросы по указанным типам.")
            return

    # 3) Список ID
    else:
        parts = [p.strip() for p in re.split(r"[;,\s]+", ids_text) if p.strip()]
        if not parts or not all(p.isdigit() for p in parts):
            await message.answer("Ожидаются только числа через запятую. Пример: 1, 5, 10")
            return
        ids = [int(p) for p in parts]

    # Сохраним в общем CSV формате ege:1, ege:5 ... или oge:...
    items = ", ".join(f"{exam}:{p}" for p in ids)
    create_group_task(group_no, title, items)
    ids_str = ", ".join(str(i) for i in ids)
    await message.answer(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {ids_str})")
    await state.set_state(None)


# ── Новые обработчики для кнопок выбора способа/типов/варианта ─────────────

@router.callback_query(lambda c: c.data.startswith("wg_tasks_method:"))
async def wg_tasks_method(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, method, exam = cb.data.split(":", 2)
    except Exception:
        await cb.answer()
        return
    if method == "ids":
        await _safe_edit_text(cb.message, "Введите IDs через запятую (например: 1, 5, 10)")
        await cb.answer()
        return
    if method == "testlist":
        # Не сбрасываем уже выбранные ID, чтобы можно было возвращаться назад и добирать задания
        prev = await state.get_data()
        prev_selected = list(prev.get("ids_selected") or [])
        await state.update_data(tasks_exam=exam, ids_selected=prev_selected, ids_list=[], current_type=None, ids_page=1)
        await _safe_edit_text(cb.message, "Выбери тест:", reply_markup=get_test_types_list_keyboard(exam))
        await cb.answer()
        return


@router.callback_query(lambda c: c.data.startswith("wg_pick_type:"))
async def wg_pick_type(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str, cnt_str = cb.data.split(":", 3)
        t = int(t_str)
        cnt = int(cnt_str)
    except Exception:
        await cb.answer()
        return
    data = await state.get_data()
    selected = dict(data.get("selected_types") or {})
    selected[t] = cnt
    await state.update_data(selected_types=selected, tasks_exam=exam)
    await cb.answer(f"Добавлено: {t}={cnt}")


@router.callback_query(lambda c: c.data == "wg_types_done")
async def wg_types_done(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    selected: dict = data.get("selected_types") or {}
    if not selected:
        await cb.answer("Список пуст", show_alert=True)
        return
    # Собираем ID по выбранным типам
    ids_collected: list[int] = []
    for t, cnt in selected.items():
        ids_collected.extend(get_question_ids_by_type(exam, int(t), int(cnt)))
    # Уникализируем
    seen = set()
    ids = [x for x in ids_collected if not (x in seen or seen.add(x))]
    if not ids:
        await cb.answer("Не удалось подобрать вопросы", show_alert=True)
        return
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or "Набор"
    items = ", ".join(f"{exam}:{p}" for p in ids)
    create_group_task(group_no, title, items)
    await cb.message.edit_text(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {', '.join(map(str, ids))})")
    await state.set_state(None)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_pick_exam:"))
async def wg_pick_exam(cb: types.CallbackQuery, state: FSMContext):
    canonical = (cb.data.split(":", 1)[1] or "ege").lower()
    if canonical not in {"ege", "oge"}:
        canonical = "ege"
    await state.update_data(tasks_exam=canonical)
    await _safe_edit_text(cb.message, "Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(canonical))
    await state.set_state(WorkGroups.waiting_tasks_ids)
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_types_back")
async def wg_types_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await cb.message.edit_text("Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_pick_test:"))
async def wg_pick_test(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str = cb.data.split(":", 2)
        t = int(t_str)
    except Exception:
        await cb.answer()
        return
    ids = get_question_ids_by_type(exam, t, 200)
    # Не сбрасываем уже выбранные ids, чтобы можно было собирать набор из нескольких типов
    prev_data = await state.get_data()
    prev_selected = list(prev_data.get("ids_selected") or [])
    await state.update_data(tasks_exam=exam, current_type=t, ids_list=ids, ids_selected=prev_selected, ids_page=1)
    # Подсветим уже выбранные ID именно этого типа
    selected_for_current_type = {qid for qid in prev_selected if qid in ids}
    await _safe_edit_text(
        cb.message,
        "Выберите задания этого типа:",
        reply_markup=get_type_ids_keyboard(ids, exam=exam, task_type=t, selected=selected_for_current_type, page=1)
    )
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_toggle_id:"))
async def wg_toggle_id(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str, id_str, page_str = cb.data.split(":", 4)
        t = int(t_str)
        qid = int(id_str)
        page = int(page_str)
    except Exception:
        await cb.answer()
        return
    data = await state.get_data()
    ids_selected = set(data.get("ids_selected") or [])
    if qid in ids_selected:
        ids_selected.remove(qid)
    else:
        ids_selected.add(qid)
    ids_list = list(data.get("ids_list") or [])
    await state.update_data(ids_selected=list(ids_selected))
    try:
        await cb.message.edit_reply_markup(reply_markup=get_type_ids_keyboard(ids_list, exam=exam, task_type=t, selected=ids_selected, page=page))
    finally:
        await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_ids_page:"))
async def wg_ids_page(cb: types.CallbackQuery, state: FSMContext):
    try:
        _, exam, t_str, page_str = cb.data.split(":", 3)
        t = int(t_str)
        page = int(page_str)
    except Exception:
        await cb.answer()
        return
    data = await state.get_data()
    ids_list = list(data.get("ids_list") or [])
    ids_selected = set(data.get("ids_selected") or [])
    await state.update_data(ids_page=page)
    try:
        await cb.message.edit_reply_markup(reply_markup=get_type_ids_keyboard(ids_list, exam=exam, task_type=t, selected=ids_selected, page=page))
    finally:
        await cb.answer()


@router.callback_query(lambda c: c.data == "wg_ids_done")
async def wg_ids_done(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or "Набор"
    ids_selected = list(data.get("ids_selected") or [])
    if not ids_selected:
        await cb.answer("Ничего не выбрано", show_alert=True)
        return
    items = ", ".join(f"{exam}:{i}" for i in ids_selected)
    create_group_task(group_no, title, items)
    await cb.message.edit_text(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {', '.join(map(str, ids_selected))})")
    await state.set_state(None)
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_methods_back")
async def wg_methods_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await _safe_edit_text(cb.message, "Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_ids_back")
async def wg_ids_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await _safe_edit_text(cb.message, "Выбери тест:", reply_markup=get_test_types_list_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_task_del:"))
async def wg_task_delete(cb: types.CallbackQuery):
    """Удаляет набор заданий и обновляет список кнопок.
    Формат callback_data: wg_task_del:<task_id>
    """
    try:
        task_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return
    group_no = delete_group_task(task_id)
    if group_no is None:
        await cb.answer("Набор не найден", show_alert=True)
        return
    tasks = list_group_tasks(group_no)
    try:
        # Обновим только клавиатуру у того же сообщения
        await cb.message.edit_reply_markup(reply_markup=get_group_tasks_kb(tasks))
    except Exception:
        # Если не получилось — отправим новое сообщение с клавиатурой
        await cb.message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    await cb.answer("Удалено")


@router.callback_query(lambda c: c.data.startswith("wg_task_print:"))
async def wg_task_print(cb: types.CallbackQuery):
    """Генерирует PDF из выбранного набора заданий (по одному на лист)."""
    try:
        task_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return
    task = get_group_task_by_id(task_id)
    if not task:
        await cb.answer("Набор не найден", show_alert=True)
        return
    # Разбираем items: "ege:1, oge:3, ege:5"
    items_raw = task.get("items") or ""
    pairs = [p.strip() for p in items_raw.split(",") if p.strip()]
    questions: list[dict] = []
    # Получаем тексты из соответствующих БД через helpers из services.groups
    from services.groups import _tests_db_path_for  # type: ignore
    import sqlite3
    for pair in pairs:
        try:
            exam, sid = pair.split(":", 1)
            qid = int(sid.strip())
            db_path = _tests_db_path_for(exam.strip().lower())
        except Exception:
            continue
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                # Подбор имён колонок
                def pick(colnames: list[str]) -> str | None:
                    try:
                        cur.execute("PRAGMA table_info(tests)")
                        cols = {r[1] for r in cur.fetchall()}
                    except Exception:
                        return None
                    for name in colnames:
                        if name in cols:
                            return name
                    return None
                q_col = pick(["question", "question_text", "text", "q_text"]) or "question"
                o_col = pick(["options", "variants", "choices", "answers"]) or None
                t_col = pick(["type", "test_type", "theme", "task_type"]) or None
                fields = [f"{q_col} AS question"]
                if o_col:
                    fields.append(f"{o_col} AS options")
                if t_col:
                    fields.append(f"{t_col} AS ttype")
                sql = f"SELECT {', '.join(fields)} FROM tests WHERE id=?"
                cur.execute(sql, (qid,))
                row = cur.fetchone()
                if row:
                    questions.append({
                        "title": f"Задание №{qid}",
                        "question": row["question"] if "question" in row.keys() else "",
                        "options": row["options"] if (o_col and "options" in row.keys()) else "",
                        "type": int(row["ttype"]) if (t_col and "ttype" in row.keys() and str(row["ttype"]).isdigit()) else None,
                        "exam": exam.strip().lower(),
                        "qid": qid,
                    })
        except Exception:
            continue
    if not questions:
        await cb.answer("Не удалось собрать задания", show_alert=True)
        return
    # Генерация PDF
    import tempfile, os
    tmp_dir = tempfile.mkdtemp(prefix="grp_pdf_")
    out_path = os.path.join(tmp_dir, f"group_set_{task_id}.pdf")
    # Строгая сортировка: сначала по типу (если есть), затем по id
    questions_sorted = sorted(
        questions,
        key=lambda q: (
            int(q.get("type")) if (q.get("type") is not None and str(q.get("type")).isdigit()) else 10**9,
            int(q.get("qid") or 0)
        )
    )
    pdf_path = render_questions_to_pdf(out_path, questions_sorted)
    # Отправляем файл
    try:
        from aiogram.types import FSInputFile
        await cb.message.answer_document(FSInputFile(pdf_path), caption=f"📄 {task.get('title')}")
    except Exception:
        await cb.answer("PDF создан, но не удалось отправить", show_alert=True)
        return
    await cb.answer("PDF готов")


@router.callback_query(lambda c: c.data.startswith("wg_task_open:"))
async def wg_task_open(cb: types.CallbackQuery):
    """Показывает состав набора: для каждого элемента выводит экзамен, тип и ID."""
    try:
        task_id = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Не понимаю id", show_alert=True)
        return
    task = get_group_task_by_id(task_id)
    if not task:
        await cb.answer("Набор не найден", show_alert=True)
        return
    # Разбираем items и достаём тип из БД соответствующего экзамена
    items_raw = task.get("items") or ""
    pairs = [p.strip() for p in items_raw.split(",") if p.strip()]
    lines: list[str] = []
    # Заголовок
    lines.append(f"Состав набора '{task.get('title') or task_id}' (группа {task.get('group_no')}):")
    lines.append("<pre>")
    try:
        from services.groups import _tests_db_path_for  # type: ignore
        import sqlite3
        for pair in pairs:
            try:
                exam, sid = pair.split(":", 1)
                qid = int(sid.strip())
                db_path = _tests_db_path_for(exam.strip().lower())
            except Exception:
                continue
            ttype: int | None = None
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.cursor()
                    # Определим имя колонки типа
                    cur.execute("PRAGMA table_info(tests)")
                    cols = {r[1] for r in cur.fetchall()}
                    type_col = "type"
                    for name in ("type", "test_type", "theme", "task_type"):
                        if name in cols:
                            type_col = name
                            break
                    cur.execute(f"SELECT {type_col} FROM tests WHERE id=?", (qid,))
                    row = cur.fetchone()
                    if row and str(row[0]).isdigit():
                        ttype = int(row[0])
            except Exception:
                ttype = None
            exam_up = (exam or "").strip().upper()
            lines.append(f"{exam_up}: тип {ttype if ttype is not None else '?'}  •  id {qid}")
    except Exception:
        # Если что-то пошло не так — хотя бы отобразим id
        for pair in pairs:
            try:
                exam, sid = pair.split(":", 1)
                qid = int(sid.strip())
            except Exception:
                continue
            lines.append(f"{(exam or '').upper()}: id {qid}")
    lines.append("</pre>")
    # Кнопка назад к списку наборов этой группы
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"wg_tasks_list:{task.get('group_no')}")]]
    )
    await cb.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_tasks_list:"))
async def wg_tasks_list(cb: types.CallbackQuery):
    """Возвращает список наборов для указанной группы (после просмотра состава)."""
    try:
        group_no = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer()
        return
    tasks = list_group_tasks(group_no)
    try:
        await cb.message.edit_text("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    except Exception:
        await cb.message.answer("У этой группы уже есть наборы:", reply_markup=get_group_tasks_kb(tasks))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_variants_page:"))
async def wg_variants_page(cb: types.CallbackQuery, state: FSMContext):
    try:
        arg = cb.data.split(":", 1)[1]
        if arg == "noop":
            await cb.answer()
            return
        page = int(arg)
    except Exception:
        page = 1
    data = await state.get_data()
    names = data.get("variants_list") or []
    await state.update_data(variants_page=page)
    await _safe_edit_text(cb.message, "Выберите вариант (filename):", reply_markup=get_variant_list_keyboard(names, page, 10))
    await cb.answer()


@router.callback_query(lambda c: c.data == "wg_variants_back")
async def wg_variants_back(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    await _safe_edit_text(cb.message, "Выберите способ добавления заданий:", reply_markup=get_task_method_keyboard(exam))
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("wg_pick_variant:"))
async def wg_pick_variant(cb: types.CallbackQuery, state: FSMContext):
    filename = cb.data.split(":", 1)[1]
    data = await state.get_data()
    exam = (data.get("tasks_exam") or "ege").lower()
    ids = get_question_ids_by_filename(exam, filename)
    if not ids:
        await cb.answer("Не нашёл вопросы по этому варианту", show_alert=True)
        return
    group_no = int(data.get("tasks_group") or 0)
    title = data.get("tasks_title") or f"Вариант {filename}"
    items = ", ".join(f"{exam}:{p}" for p in ids)
    create_group_task(group_no, title, items)
    await cb.message.edit_text(f"✅ Набор '{title}' сохранён для группы {group_no}. ({exam.upper()} IDs: {', '.join(map(str, ids))})")
    await state.set_state(None)
    await cb.answer()


@router.callback_query(lambda c: c.data.startswith("add_to_group:"))
async def add_student_to_group_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик добавления ученика в группу"""
    try:
        parts = callback.data.split(":")
        # Форматы: add_to_group:<user_id> или add_to_group:<user_id>:<page>
        user_id = int(parts[1])
        page = int(parts[2]) if len(parts) >= 3 else 1
        
        # Получаем информацию об ученике
        data = await state.get_data()
        students = data.get("students") or get_all_students_with_plans()
        student_info = None
        for student in students:
            if student["user_id"] == user_id:
                student_info = student
                break
        
        if not student_info:
            await callback.answer("Ученик не найден!")
            return
        
        # Проверяем, не добавлен ли уже ученик
        if is_student_in_group(user_id):
            await callback.answer("Ученик уже в группе!")
            return
        
        # Добавляем ученика в группу
        add_student_to_group(user_id)
        
        student_name = student_info.get("label", f"ID {user_id}")
        await callback.answer(f"✅ {student_name} добавлен в группу! Теперь он может купить тариф 'Групповые'.")

        # Обновляем список учеников и клавиатуру на той же странице
        # Обновляем кэш: заново достанем с тарифами и отметим группу
        students = get_all_students_with_plans()
        for s in students:
            s["is_in_group"] = is_student_in_group(s["user_id"])
        # Применим текущие фильтры/поиск
        only_not_in_group = bool((await state.get_data()).get("only_not_in_group"))
        search_query = (await state.get_data()).get("search_query") or ""

        filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=search_query)
        await state.update_data(students=students)
        keyboard = get_students_keyboard(
            filtered, page=page, page_size=30,
            show_plans=True,
            has_search=bool(search_query.strip()),
            only_not_in_group=only_not_in_group,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        except Exception:
            # Если не удалось отредактировать (например, старое сообщение), отправим новое
            await callback.message.answer(
                "Список всех зарегистрированных учеников:\n\n"
                "Нажмите на ученика, чтобы добавить его в группу для доступа к тарифу 'Групповые':",
                reply_markup=keyboard
            )
        
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    await message_manager.delete_user_messages_fast(callback.bot, callback.from_user.id, callback.message.chat.id)
    sent = await callback.message.answer(
        "Выберите действие:",
        reply_markup=get_teacher_keyboard()
    )
    message_manager.add_message(callback.from_user.id, sent.message_id)
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("students_page:"))
async def students_page_handler(callback: types.CallbackQuery, state: FSMContext):
    """Переключение страниц списка учеников"""
    try:
        arg = callback.data.split(":")[1]
        if arg == "noop":
            await callback.answer()
            return
        page = int(arg)
    except Exception:
        page = 1

    data = await state.get_data()
    students = data.get("students") or get_all_students_with_plans()
    if not students:
        await callback.answer("Список пуст", show_alert=True)
        return

    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])

    only_not_in_group = bool(data.get("only_not_in_group"))
    search_query = data.get("search_query") or ""
    filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=search_query)
    keyboard = get_students_keyboard(
        filtered, page=page, page_size=30,
        show_plans=True,
        has_search=bool(search_query.strip()),
        only_not_in_group=only_not_in_group,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        # Гасим загрузку
        await callback.answer()


def _apply_students_filters(students: list, *, only_not_in_group: bool, search_query: str) -> list:
    sq_raw = (search_query or "").strip().lower()
    # Поддерживаем ввод с @ и без @
    sq_no_at = sq_raw[1:] if sq_raw.startswith("@") else sq_raw
    query_variants = {sq_raw, sq_no_at}
    out = []
    for s in students:
        if only_not_in_group and s.get("is_in_group"):
            continue
        if sq_raw:
            label = (s.get("label") or "").lower()
            username = (s.get("username") or "").lower()
            username_no_at = username[1:] if username.startswith("@") else username
            full_name = (s.get("full_name") or "").lower()
            # Совпадение по любой из форм запроса
            if not any(q in label or q in username or q in username_no_at or q in full_name for q in query_variants):
                continue
        out.append(s)
    return out


async def _safe_edit_text(message_obj: types.Message, text: str, *, reply_markup=None) -> None:
    """Безопасно правит текст сообщения: если контент не меняется, тихо игнорирует ошибку.
    При иных ошибках отправляет новое сообщение."""
    try:
        await message_obj.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        # message is not modified — просто игнорируем
        return
    except Exception:
        try:
            await message_obj.answer(text, reply_markup=reply_markup)
        except Exception:
            pass


@router.callback_query(lambda c: c.data == "students_search")
async def students_start_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите часть имени или username для поиска (или отправьте пусто, чтобы сбросить):")
    await state.set_state(StudentsList.waiting_search_query)


@router.message(StudentsList.waiting_search_query)
async def students_apply_search(message: types.Message, state: FSMContext):
    query = (message.text or "").strip()
    data = await state.get_data()
    students = data.get("students") or get_all_students_with_plans()

    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])

    only_not_in_group = bool(data.get("only_not_in_group"))
    filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=query)
    await state.update_data(search_query=query, students=students)

    keyboard = get_students_keyboard(
        filtered, page=1, page_size=30,
        show_plans=True,
        has_search=bool(query),
        only_not_in_group=only_not_in_group,
    )
    await message.answer(
        "Результаты поиска. Листайте страницы ⬅️➡️ или сбросьте фильтры.",
        reply_markup=keyboard,
    )
    await state.set_state(None)


@router.callback_query(lambda c: c.data == "students_toggle_filter")
async def students_toggle_only_not_in_group(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    students = data.get("students") or get_all_students_with_plans()
    only_not_in_group = not bool(data.get("only_not_in_group"))
    search_query = data.get("search_query") or ""

    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])

    filtered = _apply_students_filters(students, only_not_in_group=only_not_in_group, search_query=search_query)
    await state.update_data(only_not_in_group=only_not_in_group, students=students)

    keyboard = get_students_keyboard(
        filtered, page=1, page_size=30,
        show_plans=True,
        has_search=bool(search_query.strip()),
        only_not_in_group=only_not_in_group,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        await callback.answer()


@router.callback_query(lambda c: c.data == "students_clear")
async def students_clear_filters(callback: types.CallbackQuery, state: FSMContext):
    students = get_all_students_with_plans()
    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])
    await state.update_data(students=students, search_query="", only_not_in_group=False)

    keyboard = get_students_keyboard(
        students, page=1, page_size=30,
        show_plans=True,
        has_search=False,
        only_not_in_group=False,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        await callback.answer()


@router.callback_query(lambda c: c.data == "students_show_group_only")
async def students_show_group_only(callback: types.CallbackQuery, state: FSMContext):
    """Быстрый переход к списку учеников, уже добавленных в группу (как в кнопке главного меню)."""
    students = get_all_students_with_plans()
    for s in students:
        s["is_in_group"] = is_student_in_group(s["user_id"])
    students = [s for s in students if s.get("is_in_group")]

    await state.update_data(
        students=students,
        only_not_in_group=False,
        search_query="",
    )

    keyboard = get_students_keyboard(
        students, page=1, page_size=30,
        show_plans=True,
        has_search=False,
        only_not_in_group=False,
        show_controls=True,
        show_only_not_in_group_toggle=False,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    finally:
        await callback.answer()


@router.message(StateFilter('*'), lambda m: m.text == "📣 Статистика рекламы")
async def show_ads_stats(message: types.Message, state: FSMContext):
    await state.clear()
    rows = get_ad_stats()
    if not rows:
        await message.answer("Пока нет данных по рекламе.")
        return
    # Подготовим данные и итоги
    data = []
    total_started = 0
    total_subscribed = 0
    for tag, started, subscribed in rows:
        shown_tag = tag if tag and tag != "(empty)" else "(без метки)"
        total_started += int(started or 0)
        total_subscribed += int(subscribed or 0)
        cr = (int(subscribed or 0) * 100.0 / int(started or 1)) if int(started or 0) else 0.0
        data.append((shown_tag, int(started or 0), int(subscribed or 0), cr))

    # Сортировка по старте desc
    data.sort(key=lambda r: r[1], reverse=True)

    # Вычислим ширины колонок
    tag_w = max(10, max(len(r[0]) for r in data))
    s_w = max(7, len("started"))
    sub_w = max(10, len("subscribed"))
    cr_w = len("CR%")

    def row_line(tag: str, s: int, sub: int, cr: float) -> str:
        return f"{tag.ljust(tag_w)}  {str(s).rjust(s_w)}  {str(sub).rjust(sub_w)}  {int(round(cr)):>3}%"

    total_cr = (total_subscribed * 100.0 / total_started) if total_started else 0.0
    header = f"{'tag'.ljust(tag_w)}  {'started'.rjust(s_w)}  {'subscribed'.rjust(sub_w)}  CR%"
    lines = [
        "<b>Статистика по меткам</b>",
        "<pre>",
        header,
        "-" * (tag_w + s_w + sub_w + 8),
        row_line("ИТОГО", total_started, total_subscribed, total_cr),
        "",
    ]
    for tag, s, sub, cr in data:
        lines.append(row_line(tag, s, sub, cr))
    lines.append("</pre>")

    # Подсказка, если много строк без метки
    if any(tag == "(без метки)" for tag, *_ in data):
        lines.append(f"Пользователи без метки заходили не по deep-link. Используйте ссылку вида {DEEPLINK_HINT}")

    await message.answer("\n".join(lines), parse_mode="HTML")
