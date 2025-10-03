from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_teacher_keyboard():
    kb = [
        [KeyboardButton(text="👨‍🎓 Ученики онлайн"), KeyboardButton(text="📈 Успеваемость")],
        [KeyboardButton(text="🛠 Управление заданиями"), KeyboardButton(text="📚 Управление группами")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_manage_groups_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="➕ Добрать в рабочие группы", callback_data="wg_add_start")],
        [InlineKeyboardButton(text="📝 Отправить сообщение", callback_data="wg_broadcast_start")],
        [InlineKeyboardButton(text="🧩 Задания для группы", callback_data="wg_tasks_start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_group_tasks_kb(tasks: list[dict], group_no: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for t in tasks:
        title = t.get("title") or f"Набор {t.get('id')}"
        # Одна строка: название | 📊 | 🖨 | 🗑
        open_btn = InlineKeyboardButton(text=title, callback_data=f"wg_task_open:{t.get('id')}")
        stats_btn = InlineKeyboardButton(text="📊", callback_data=f"wg_task_results:{t.get('id')}")
        print_btn = InlineKeyboardButton(text="🖨", callback_data=f"wg_task_print:{t.get('id')}")
        del_btn = InlineKeyboardButton(text="🗑", callback_data=f"wg_task_del:{t.get('id')}")
        rows.append([open_btn, stats_btn, print_btn, del_btn])
    # Кнопка создания нового набора — перед кнопкой Назад
    if group_no is not None:
        rows.append([InlineKeyboardButton(text="➕ Создать задание", callback_data=f"wg_task_create:{group_no}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_group_numbers_keyboard(group_numbers: list[int]) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    for g in group_numbers:
        kb.append([InlineKeyboardButton(text=f"Группа {g}", callback_data=f"wg_open:{g}")])
    # Кнопка создания новой группы в этом списке
    kb.append([InlineKeyboardButton(text="➕ Создать новую группу", callback_data="wg_add_start")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_group_pick_keyboard(
    group_numbers: list[int], *, prefix: str, back_cb: str = "manage_groups_back", include_create: bool = False
) -> InlineKeyboardMarkup:
    """Универсальная клавиатура выбора группы по списку номеров.
    prefix — префикс callback_data, будет отправлено `<prefix>:<group_no>`.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for g in group_numbers:
        rows.append([InlineKeyboardButton(text=f"Группа {g}", callback_data=f"{prefix}:{g}")])
    if include_create:
        rows.append([InlineKeyboardButton(text="➕ Создать новую группу", callback_data="wg_create_group")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_group_members_keyboard(members: list[dict], group_no: int | None = None, *, back_cb: str = "manage_groups_list") -> InlineKeyboardMarkup:
    """Список участников. Оставляем только кнопку исключения из рабочей группы:
    - 🚫 Исключить из рабочей группы (work_groups), если передан group_no
    """
    kb: list[list[InlineKeyboardButton]] = []
    for s in members:
        uid = s.get("user_id")
        # Базовая подпись
        label = s.get("label") or s.get("full_name") or s.get("username") or f"ID {uid}"
        if len(label) > 30:
            label = label[:27] + "…"
        # Короткая метка тарифа, если есть данные
        plan_code = (s.get("plan_code") or "").lower()
        plan_name = (s.get("plan_name") or "").lower()
        code = plan_code or plan_name
        short = ""
        if code:
            mapping = {
                "free": "Беспл.",
                "group": "Групп.",
                "self": "Самост.",
                "organic": "Орган.",
                "elements": "Элем.",
                "full": "Полный",
            }
            for key, short_name in mapping.items():
                if key in code:
                    short = short_name
                    break
        text = f"{label} • {short}" if short else label
        row: list[InlineKeyboardButton] = [InlineKeyboardButton(text=text, callback_data=f"noop_member:{uid}")]
        if group_no is not None:
            row.append(InlineKeyboardButton(text="🚫", callback_data=f"wg_wremove:{group_no}:{uid}"))
        kb.append(row)
    # Кнопка добавления нового участника в эту группу
    if group_no is not None:
        kb.append([InlineKeyboardButton(text="➕ Добавить в группу", callback_data=f"wg_prompt_add:{group_no}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_manage_tasks_keyboard():
    kb = [
        [KeyboardButton(text="➕ Добавить")],
        [KeyboardButton(text="🛠 Исправить")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_task_method_keyboard(exam: str) -> InlineKeyboardMarkup:
    # Упрощённый интерфейс: список тестов как в govr-боте + ручной ввод ID
    kb = [
        [InlineKeyboardButton(text="🧪 Список тестов", callback_data=f"wg_tasks_method:testlist:{exam}")],
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
            InlineKeyboardButton(text="Задания преподавателя", callback_data="wg_pick_exam:teacher"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_groups_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_test_types_list_keyboard(exam: str) -> InlineKeyboardMarkup:
    """Клавиатура списка тестов (типов) как в govr-боте: Тест 1..N."""
    max_type = 28 if (exam or "").lower() == "ege" else 19
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for t in range(1, max_type + 1):
        row.append(InlineKeyboardButton(text=f"Тест {t}", callback_data=f"wg_pick_test:{exam}:{t}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="wg_methods_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_teacher_sets_keyboard(sets: list[dict]) -> InlineKeyboardMarkup:
    """Список наборов из test_teacher.db для назначения группе."""
    rows: list[list[InlineKeyboardButton]] = []
    for s in sets:
        title = s.get("title") or f"Набор {s.get('id')}"
        if len(title) > 40:
            title = title[:37] + "…"
        sid = s.get("id")
        rows.append([InlineKeyboardButton(text=title, callback_data=f"wg_pick_teacher_set:{sid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="wg_teacher_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_type_ids_keyboard(ids: list[int], *, exam: str, task_type: int, selected: set[int] | None = None, page: int = 1, page_size: int = 21) -> InlineKeyboardMarkup:
    """Построение клавиатуры со списком ID заданий указанного типа.
    Выделяет выбранные ID значком ✅. Есть пагинация и кнопка Готово.
    """
    selected = selected or set()
    total = max(0, len(ids))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = min(start + page_size, total)

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for qid in ids[start:end]:
        mark = "✅ " if qid in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{qid}", callback_data=f"wg_toggle_id:{exam}:{task_type}:{qid}:{page}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if total_pages > 1:
        prev_page = page - 1 if page > 1 else page
        next_page = page + 1 if page < total_pages else page
        rows.append([
            InlineKeyboardButton(text="⬅️", callback_data=f"wg_ids_page:{exam}:{task_type}:{prev_page}"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="wg_ids_page:noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"wg_ids_page:{exam}:{task_type}:{next_page}"),
        ])
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="wg_ids_done")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="wg_ids_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

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

        row = [
            InlineKeyboardButton(
                text=text,
                callback_data=f"add_to_group:{student['user_id']}:{page}"
            )
        ]
        # Если уже в группе — показываем корзину для быстрого удаления из общей группы
        if is_in_group:
            row.append(
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"wg_remove:{student['user_id']}:{page}"
                )
            )
        kb.append(row)

    # Ряд с контролами поиска/фильтра
    if show_controls:
        controls_row = [
            InlineKeyboardButton(
                text=("🔎 Поиск" if not has_search else "🔎 Поиск: вкл"),
                callback_data="students_search"
            ),
            # Если сейчас идёт поиск — показываем Сброс, иначе — быстрый переход к списку учеников в группе
            InlineKeyboardButton(
                text=("🧹 Сброс" if has_search else "✅ Ученики в группе"),
                callback_data=("students_clear" if has_search else "students_show_group_only")
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
