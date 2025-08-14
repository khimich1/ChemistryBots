from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from bot.services.db import get_user, upsert_user, init_users_db
from bot.services.gpt_service import chat_with_gpt
from aiogram.fsm.state import State, StatesGroup


router = Router()


class Onboarding(StatesGroup):
    waiting_parent_name = State()
    waiting_child_nick = State()


main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Отчёт об успеваемости")],
        [KeyboardButton(text="💳 Оплата занятий")],
        [KeyboardButton(text="🤖 Доступ к GPT")],
    ],
    resize_keyboard=True,
)


@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    init_users_db()
    upsert_user(message.from_user.id)
    await state.set_state(Onboarding.waiting_parent_name)
    await message.answer("Здравствуйте! Как вас зовут? Напишите имя и фамилию.")


@router.message(Onboarding.waiting_parent_name)
async def parent_name_received(message: Message, state: FSMContext):
    upsert_user(message.from_user.id, parent_name=message.text.strip())
    await state.set_state(Onboarding.waiting_child_nick)
    await message.answer("Отлично! Теперь пришлите ник в Telegram вашего ребёнка (например, @nickname)")


@router.message(Onboarding.waiting_child_nick)
async def child_nick_received(message: Message, state: FSMContext):
    upsert_user(message.from_user.id, child_nick=message.text.strip())
    await state.clear()
    await message.answer("Спасибо! Данные сохранены.", reply_markup=main_kb)


@router.message(F.text.in_({"📊 Отчёт об успеваемости", "💳 Оплата занятий"}))
async def stubs(message: Message):
    if message.text == "📊 Отчёт об успеваемости":
        await message.answer("Отчёт об успеваемости: скоро будет доступен.")
    else:
        await message.answer("Оплата занятий: скоро будет доступна.")


@router.message(F.text == "🤖 Доступ к GPT")
async def gpt_entry(message: Message):
    user = get_user(message.from_user.id)
    parent_name = user[0] if user else "родитель"
    await message.answer(
        "Напишите сообщение для GPT. История последних 20 сообщений сохраняется.\n"
        "Чтобы очистить память, отправьте: /reset"
    )


@router.message(F.text & ~F.text.in_({"📊 Отчёт об успеваемости", "💳 Оплата занятий", "🤖 Доступ к GPT"}))
async def gpt_chat(message: Message):
    user = get_user(message.from_user.id)
    parent_name = user[0] if user else "родитель"
    system = f"Ты дружелюбный ассистент для родителя по имени {parent_name}. Отвечай кратко и по делу."
    try:
        answer = await chat_with_gpt(message.from_user.id, system, message.text)
    except Exception as e:
        await message.answer(f"GPT недоступен: {e}")
        return
    await message.answer(answer)


