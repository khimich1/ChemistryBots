from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_teacher_keyboard():
    kb = [
        [KeyboardButton(text="👨‍🎓 Ученики онлайн"), KeyboardButton(text="📈 Успеваемость")],
        [KeyboardButton(text="🛠 Управление заданиями"), KeyboardButton(text="👥 Добавить в группу")],
        [KeyboardButton(text="✅ Ученики в группе"), KeyboardButton(text="📚 Управление группами")],
        [KeyboardButton(text="📣 Статистика рекламы")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_manage_groups_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="📂 Список групп", callback_data="manage_groups_list")],
        [InlineKeyboardButton(text="➕ Добрать в рабочие группы", callback_data="wg_add_start")],
        [InlineKeyboardButton(text="📝 Отправить сообщение", callback_data="wg_broadcast_start")],
        [InlineKeyboardButton(text="🧩 Задания для группы", callback_data="wg_tasks_start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_group_tasks_kb(tasks: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for t in tasks:
        rows.append([InlineKeyboardButton(text=t.get("title") or f"Набор {t.get('id')}", callback_data=f"wg_task_open:{t.get('id')}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_group_numbers_keyboard(group_numbers: list[int]) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    for g in group_numbers:
        kb.append([InlineKeyboardButton(text=f"Группа {g}", callback_data=f"wg_open:{g}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_group_members_keyboard(members: list[dict]) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    for s in members:
        label = s.get("label") or s.get("full_name") or s.get("username") or f"ID {s.get('user_id')}"
        if len(label) > 30:
            label = label[:27] + "…"
        kb.append([InlineKeyboardButton(text=label, callback_data=f"noop_member:{s.get('user_id')}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_list")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_manage_tasks_keyboard():
    kb = [
        [KeyboardButton(text="➕ Добавить")],
        [KeyboardButton(text="🛠 Исправить")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_students_keyboard(
    students: list,
    page: int = 1,
    page_size: int = 30,
    *,
    show_plans: bool = True,
    has_search: bool = False,
    only_not_in_group: bool = False,
    show_controls: bool = True,
    show_only_not_in_group_toggle: bool = True,
) -> InlineKeyboardMarkup:
    """Создает пагинированную клавиатуру со списком учеников с контролами.
    page — номер страницы с 1, page_size — количество строк на страницу.
    show_plans — показывать ли тариф рядом с учеником.
    has_search — включён ли фильтр по поиску (для индикации).
    only_not_in_group — фильтр "только без группы" (для индикации).
    """
    total = max(0, len(students))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    end = min(start + page_size, total)

    kb = []

    def _short_plan(student: dict) -> str:
        plan_code = (student.get("plan_code") or "").lower()
        plan_name = (student.get("plan_name") or "").lower()
        code = plan_code or plan_name
        mapping = {
            "free": "Беспл.",
            "group": "Групп.",
            "self": "Самост.",
            "organic": "Орган.",
            "elements": "Элем.",
            "full": "Полный",
        }
        for key, short in mapping.items():
            if key in code:
                return short
        # Фолбэк: первые 8 символов названия
        return (student.get("plan_name") or "").strip()[:8] or ""

    for student in students[start:end]:
        label = student.get("label", f"ID {student['user_id']}")
        if len(label) > 18:
            label = label[:16] + "…"

        is_in_group = student.get("is_in_group", False)
        status_icon = "✅" if is_in_group else "➕"
        parts = [label]
        if show_plans:
            plan_short = _short_plan(student)
            if plan_short:
                parts.append(plan_short)
        parts.append(status_icon)
        text = " • ".join(parts)

        kb.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"add_to_group:{student['user_id']}:{page}"
            )
        ])

    # Ряд с контролами поиска/фильтра
    if show_controls:
        controls_row = [
            InlineKeyboardButton(
                text=("🔎 Поиск" if not has_search else "🔎 Поиск: вкл"),
                callback_data="students_search"
            ),
            InlineKeyboardButton(
                text=("🧹 Сброс" if has_search else "↻ Обновить"),
                callback_data="students_clear"
            ),
        ]
        if show_only_not_in_group_toggle:
            controls_row.append(
                InlineKeyboardButton(
                    text=("🚫 Только без группы: ВКЛ" if only_not_in_group else "🚫 Только без группы: ВЫКЛ"),
                    callback_data="students_toggle_filter"
                )
            )
        kb.append(controls_row)

    # Навигация по страницам (если страниц больше одной)
    if total_pages > 1:
        nav_row = []
        # Кнопка Назад
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"students_page:{page-1}"))
        else:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"students_page:{page}"))
        # Текущая страница
        nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="students_page:noop"))
        # Кнопка Вперёд
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"students_page:{page+1}"))
        else:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"students_page:{page}"))
        kb.append(nav_row)

    # Кнопка "Назад" в главное меню
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])

    return InlineKeyboardMarkup(inline_keyboard=kb)
