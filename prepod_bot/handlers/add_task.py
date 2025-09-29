from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import StateFilter

from keyboards import get_manage_tasks_keyboard, get_teacher_keyboard
from services.tasks import (
    list_problem_tasks,
    get_task_by_id,
    update_task_field,
    unhide_task,
)
from states import EditTask
from utils.message_manager import message_manager

router = Router()

@router.message(StateFilter('*'), lambda m: m.text == "🛠 Управление заданиями")
async def manage_tasks_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    sent = await message.answer("Выберите действие:", reply_markup=get_manage_tasks_keyboard())
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(StateFilter('*'), lambda m: m.text == "⬅️ Назад")
async def manage_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message_manager.delete_user_messages_fast(message.bot, message.from_user.id, message.chat.id)
    sent = await message.answer("Главное меню:", reply_markup=get_teacher_keyboard())
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(lambda m: m.text == "➕ Добавить")
async def manage_add_placeholder(message: types.Message):
    sent = await message.answer("Функция добавления появится позже.")
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


@router.message(lambda m: m.text == "🛠 Исправить")
async def manage_fix_list(message: types.Message):
    tasks = list_problem_tasks()
    if not tasks:
        sent = await message.answer("Нет скрытых заданий.")
        try:
            message_manager.add_message(message.from_user.id, sent.message_id)
        except Exception:
            pass
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{t['id']} • {t['question'][:32]}…", callback_data=f"dbg_task_{t['id']}")]
        for t in tasks
    ])
    sent = await message.answer("Выберите задание для правки:", reply_markup=kb)
    try:
        message_manager.add_message(message.from_user.id, sent.message_id)
    except Exception:
        pass


def _edit_task_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать текст задания", callback_data=f"dbg_edit_q_{task_id}")],
        [InlineKeyboardButton(text="✏️ Редактировать варианты", callback_data=f"dbg_edit_opts_{task_id}")],
        [InlineKeyboardButton(text="✏️ Редактировать верный ответ", callback_data=f"dbg_edit_ans_{task_id}")],
        [InlineKeyboardButton(text="✏️ Редактировать подсказку", callback_data=f"dbg_edit_hint_{task_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="dbg_back")],
        [InlineKeyboardButton(text="✅ Отображать вновь", callback_data=f"dbg_unhide_{task_id}")],
    ])


@router.callback_query(lambda c: c.data and c.data.startswith("dbg_task_"))
async def open_task(cb: types.CallbackQuery):
    task_id = int(cb.data.split("_")[-1])
    task = get_task_by_id(task_id)
    if not task:
        await cb.answer("Задание не найдено", show_alert=True)
        return
    text = (
        f"Задание #{task['id']}\n\n"
        f"{task['question']}\n\n"
        f"Варианты:\n{task['options']}\n\n"
        f"Верный ответ: {task['correct_answer']}\n\n"
        f"Подсказка: {task.get('hint','')}"
    )
    try:
        await cb.message.edit_text(text)
        await cb.message.edit_reply_markup(reply_markup=_edit_task_kb(task_id))
    except Exception:
        sent = await cb.message.answer(text, reply_markup=_edit_task_kb(task_id))
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    await cb.answer()


@router.callback_query(lambda c: c.data == "dbg_back")
async def back_to_list(cb: types.CallbackQuery):
    tasks = list_problem_tasks()
    if not tasks:
        try:
            await cb.message.edit_text("Нет скрытых заданий.")
        except Exception:
            sent = await cb.message.answer("Нет скрытых заданий.")
            try:
                message_manager.add_message(cb.from_user.id, sent.message_id)
            except Exception:
                pass
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{t['id']} • {t['question'][:32]}…", callback_data=f"dbg_task_{t['id']}")]
        for t in tasks
    ])
    try:
        await cb.message.edit_text("Выберите задание для правки:")
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        sent = await cb.message.answer("Выберите задание для правки:", reply_markup=kb)
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    await cb.answer()


@router.callback_query(lambda c: c.data and (c.data.startswith("dbg_edit_q_") or c.data.startswith("dbg_edit_opts_") or c.data.startswith("dbg_edit_ans_") or c.data.startswith("dbg_edit_hint_")))
async def ask_new_text(cb: types.CallbackQuery, state: FSMContext):
    data = cb.data
    if data.startswith("dbg_edit_q_"):
        field = "question"
    elif data.startswith("dbg_edit_opts_"):
        field = "options"
    elif data.startswith("dbg_edit_ans_"):
        field = "correct_answer"
    else:
        field = "hint"
    task_id = int(data.split("_")[-1])
    await state.set_state(EditTask.waiting_new_text)
    await state.update_data(edit_task_id=task_id, edit_field=field)
    sent = await cb.message.answer("Пришлите новый текст:")
    try:
        message_manager.add_message(cb.from_user.id, sent.message_id)
    except Exception:
        pass
    await cb.answer()


@router.message(EditTask.waiting_new_text)
async def save_new_text(m: types.Message, state: FSMContext):
    data = await state.get_data()
    task_id = int(data["edit_task_id"])
    field = data["edit_field"]
    new_text = (m.text or "").strip()
    update_task_field(task_id, field, new_text)
    await state.clear()
    # Перепокажем карточку задания
    task = get_task_by_id(task_id)
    text = (
        f"Задание #{task['id']}\n\n"
        f"{task['question']}\n\n"
        f"Варианты:\n{task['options']}\n\n"
        f"Верный ответ: {task['correct_answer']}\n\n"
        f"Подсказка: {task.get('hint','')}"
    )
    sent1 = await m.answer("Изменения сохранены.")
    sent2 = await m.answer(text, reply_markup=_edit_task_kb(task_id))
    try:
        message_manager.add_message(m.from_user.id, sent1.message_id)
        message_manager.add_message(m.from_user.id, sent2.message_id)
    except Exception:
        pass


@router.callback_query(lambda c: c.data and c.data.startswith("dbg_unhide_"))
async def unhide_and_back(cb: types.CallbackQuery):
    task_id = int(cb.data.split("_")[-1])
    unhide_task(task_id)
    # Покажем обновлённый список
    tasks = list_problem_tasks()
    if not tasks:
        try:
            await cb.message.edit_text("Готово. Все исправлено, скрытых заданий нет.")
        except Exception:
            sent = await cb.message.answer("Готово. Все исправлено, скрытых заданий нет.")
            try:
                message_manager.add_message(cb.from_user.id, sent.message_id)
            except Exception:
                pass
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{t['id']} • {t['question'][:32]}…", callback_data=f"dbg_task_{t['id']}")]
        for t in tasks
    ])
    try:
        await cb.message.edit_text("Задание возвращено в выдачу. Выберите следующее:")
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        sent = await cb.message.answer("Задание возвращено в выдачу. Выберите следующее:", reply_markup=kb)
        try:
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    await cb.answer()
