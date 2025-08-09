from aiogram import Router, types
from aiogram.filters import Command
from keyboards import get_teacher_keyboard

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я помощник преподавателя. Выберите действие:",
        reply_markup=get_teacher_keyboard()
    )
