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
        title = t.get("title") or f"Набор {t.get('id')}"
        # Одна строка, три столбца: название | 🖨 | 🗑
        open_btn = InlineKeyboardButton(text=title, callback_data=f"wg_task_open:{t.get('id')}")
        print_btn = InlineKeyboardButton(text="🖨", callback_data=f"wg_task_print:{t.get('id')}")
        del_btn = InlineKeyboardButton(text="🗑", callback_data=f"wg_task_del:{t.get('id')}")
        rows.append([open_btn, print_btn, del_btn])
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


def get_task_method_keyboard(exam: str) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="📚 По типам и количеству", callback_data=f"wg_tasks_method:types:{exam}")],
        [InlineKeyboardButton(text="🗂 По варианту (filename)", callback_data=f"wg_tasks_method:variant:{exam}")],
        [InlineKeyboardButton(text="🔢 Ввести ID вручную", callback_data=f"wg_tasks_method:ids:{exam}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_task_types_keyboard(exam: str) -> InlineKeyboardMarkup:
    # Показываем кнопки типов 1..28 / 1..19 с быстрыми вариантами количества
    max_type = 28 if (exam or "").lower() == "ege" else 19
    kb: list[list[InlineKeyboardButton]] = []
    for t in range(1, max_type + 1):
        kb.append([
            InlineKeyboardButton(text=f"Задание {t} • 1", callback_data=f"wg_pick_type:{exam}:{t}:1"),
            InlineKeyboardButton(text="5", callback_data=f"wg_pick_type:{exam}:{t}:5"),
            InlineKeyboardButton(text="10", callback_data=f"wg_pick_type:{exam}:{t}:10"),
        ])
    kb.append([InlineKeyboardButton(text="✅ Готово", callback_data="wg_types_done")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="wg_types_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_variant_list_keyboard(filenames: list[str], page: int = 1, page_size: int = 10) -> InlineKeyboardMarkup:
    total = max(0, len(filenames))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    kb: list[list[InlineKeyboardButton]] = []
    for name in filenames[start:end]:
        shown = name
        if len(shown) > 40:
            shown = shown[:37] + "…"
        kb.append([InlineKeyboardButton(text=shown, callback_data=f"wg_pick_variant:{name}")])
    # навигация
    if total_pages > 1:
        nav = []
        prev_page = page - 1 if page > 1 else page
        next_page = page + 1 if page < total_pages else page
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"wg_variants_page:{prev_page}"))
        nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="wg_variants_page:noop"))
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"wg_variants_page:{next_page}"))
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="wg_variants_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_exam_pick_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора базы заданий (ЕГЭ/ОГЭ)."""
    kb = [
        [
            InlineKeyboardButton(text="ЕГЭ", callback_data="wg_pick_exam:ege"),
            InlineKeyboardButton(text="ОГЭ", callback_data="wg_pick_exam:oge"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

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
