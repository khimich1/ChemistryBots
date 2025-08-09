from aiogram import Router, types

router = Router()

@router.message(lambda m: m.text == "➕ Добавить задание")
async def add_task_start(message: types.Message):
    await message.answer("Здесь будет диалог добавления нового задания.")
