import os
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from ..states import TariffForm
from ..keyboards import (
    build_main_menu,
    build_confirm_all_kb,
    build_correction_field_kb,
    build_edit_profile_kb,
    build_links_kb,
)
from ..services.db import get_db

logger = logging.getLogger(__name__)

router = Router(name="admin_menu")


WELCOME_TEXT = (
    "Привет! Это Admin_bot проекта ChemistryBots.\n\n"
    "Мы сделали набор ботов, чтобы репетитору было проще готовить учеников к экзаменам: "
    "тесты, карточки, отчёты — всё под рукой. Этот бот поможет зарегистрироваться "
    "как преподавателю и выбрать тариф."
)

ABOUT_TEXT = (
    "О проекте:\n\n"
    "- Govr Bot: бот для учеников с тестами, карточками и материалами.\n"
    "- Prepod Bot: бот для преподавателя — отчёты, группы, задания.\n"
    "- Parent Bot: бот для родителей — прогресс и отчётность.\n\n"
    "Admin_bot — ваш вход в систему: регистрация и управление тарифом."
)


def _format_summary(data: dict) -> str:
    return (
        "Проверьте ваши данные:\n\n"
        f"1) ФИО: {data.get('name','')}\n"
        f"2) Предмет: {data.get('discipline','')}\n"
        f"3) Обращение: {data.get('moniker','')}\n\n"
        "Если всё верно — подтвердите. Если нужно — исправьте."
    )


def _format_profile(teacher: dict) -> str:
    rate = teacher.get("rate") or "Пробная версия"
    return (
        "Ваш профиль:\n\n"
        f"• ФИО: {teacher.get('name','')}\n"
        f"• Предмет: {teacher.get('discipline','')}\n"
        f"• Обращение: {teacher.get('moniker','')}\n"
        f"• Тариф: {rate}"
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} (@{message.from_user.username}) started bot")
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=build_main_menu())


@router.message(F.text.casefold() == "о проекте")
async def about_project(message: Message) -> None:
    await message.answer(ABOUT_TEXT)


@router.message(F.text.casefold() == "бот для учеников")
async def link_students_bot(message: Message) -> None:
    student_url = os.getenv("STUDENT_BOT_URL")
    if not student_url:
        await message.answer("Ссылка на бот для учеников не настроена в .env (STUDENT_BOT_URL).")
        return
    await message.answer("Ссылка на бот для учеников:", reply_markup=build_links_kb(student_url, None))


@router.message(F.text.casefold() == "бот для преподавателей")
async def link_teachers_bot(message: Message) -> None:
    teacher_url = os.getenv("TEACHER_BOT_URL")
    if not teacher_url:
        await message.answer("Ссылка на бот для преподавателей не настроена в .env (TEACHER_BOT_URL).")
        return
    await message.answer("Ссылка на бот для преподавателей:", reply_markup=build_links_kb(None, teacher_url))


@router.message(F.text.casefold() == "мой тариф")
async def start_tariff(message: Message, state: FSMContext) -> None:
    await state.clear()
    db = get_db()
    db.ensure_teacher_table()
    teacher = db.get_teacher_by_tg_id(message.from_user.id)
    if teacher:
        await message.answer(_format_profile(teacher), reply_markup=build_edit_profile_kb())
        return
    await state.set_state(TariffForm.name)
    await message.answer("1) Ваше ФИО (Имя Фамилия Отчество):")


@router.callback_query(F.data == "profile:edit")
async def edit_profile(callback: CallbackQuery, state: FSMContext) -> None:
    db = get_db()
    teacher = db.get_teacher_by_tg_id(callback.from_user.id)
    if not teacher:
        await callback.message.edit_text("Профиль не найден. Давайте начнём регистрацию.")
        await state.clear()
        await state.set_state(TariffForm.name)
        await callback.message.answer("1) Ваше ФИО (Имя Фамилия Отчество):")
        return
    # Предзаполняем данные для коррекции
    await state.clear()
    await state.update_data(
        name=teacher.get("name", ""),
        discipline=teacher.get("discipline", ""),
        moniker=teacher.get("moniker", ""),
        correction_index=0,
    )
    await state.set_state(TariffForm.correcting)
    await _send_correction_prompt(callback, state)


@router.message(TariffForm.name)
async def ask_discipline(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(TariffForm.discipline)
    await message.answer("2) Какой предмет вы преподаёте?")


@router.message(TariffForm.discipline)
async def ask_moniker(message: Message, state: FSMContext) -> None:
    await state.update_data(discipline=message.text.strip())
    await state.set_state(TariffForm.moniker)
    await message.answer(
        "3) Как к вам обращаются ученики?\n"
        "Например: Рома, Роман Алексеевич, Господин Учитель, Сенсей"
    )


@router.message(TariffForm.moniker)
async def show_summary(message: Message, state: FSMContext) -> None:
    await state.update_data(moniker=message.text.strip())
    data = await state.get_data()
    await state.set_state(TariffForm.confirming)
    await message.answer(_format_summary(data), reply_markup=build_confirm_all_kb())


@router.callback_query(F.data == "confirm_all", TariffForm.confirming)
async def confirm_all(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    user = callback.from_user
    teacher = {
        "tg_id": user.id,
        "nickname": user.username or "",
        "name": data.get("name", ""),
        "moniker": data.get("moniker", ""),
        "discipline": data.get("discipline", ""),
        "rate": None,
    }
    db = get_db()
    db.ensure_teacher_table()
    db.upsert_teacher(teacher)

    logger.info(f"Teacher registered: {teacher['name']} ({teacher['discipline']}) - @{teacher['nickname']} (ID: {teacher['tg_id']})")
    await state.clear()
    await callback.message.edit_text("✅ Данные сохранены! Вы в главном меню.")


FIELDS_ORDER = [
    ("name", "ФИО"),
    ("discipline", "Предмет"),
    ("moniker", "Обращение"),
]


async def _send_correction_prompt(callback_or_message, state: FSMContext) -> None:
    data = await state.get_data()
    index = int(data.get("correction_index", 0))
    if index >= len(FIELDS_ORDER):
        # Возвращаемся к сводке
        await state.set_state(TariffForm.confirming)
        await callback_or_message.answer(_format_summary(await state.get_data()), reply_markup=build_confirm_all_kb())
        return

    field_key, field_title = FIELDS_ORDER[index]
    value = data.get(field_key, "")
    text = f"{index + 1}) {field_title}: {value}\nПодтвердить или отредактировать?"

    if isinstance(callback_or_message, CallbackQuery):
        await callback_or_message.message.edit_text(text, reply_markup=build_correction_field_kb())
    else:
        await callback_or_message.answer(text, reply_markup=build_correction_field_kb())


@router.callback_query(F.data == "correct_all", TariffForm.confirming)
async def start_correction(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(correction_index=0)
    await state.set_state(TariffForm.correcting)
    await _send_correction_prompt(callback, state)


@router.callback_query(F.data == "corr:confirm", TariffForm.correcting)
async def corr_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    index = int(data.get("correction_index", 0))
    await state.update_data(correction_index=index + 1)
    await _send_correction_prompt(callback, state)


@router.callback_query(F.data == "corr:edit", TariffForm.correcting)
async def corr_edit(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    index = int(data.get("correction_index", 0))
    _, field_title = FIELDS_ORDER[index]
    await state.set_state(TariffForm.editing_field)
    await callback.message.edit_text(f"Введите новое значение для поля: {field_title}")


@router.message(TariffForm.editing_field)
async def corr_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    index = int(data.get("correction_index", 0))
    field_key, _ = FIELDS_ORDER[index]
    await state.update_data(**{field_key: message.text.strip()})
    # После редактирования считаем поле подтверждённым и двигаемся дальше
    await state.update_data(correction_index=index + 1)
    await state.set_state(TariffForm.correcting)
    await _send_correction_prompt(message, state)
