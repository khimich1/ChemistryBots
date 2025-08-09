from aiogram import Router, types

router = Router()

@router.message(lambda m: m.text == "📈 Успеваемость")
async def show_report(message: types.Message):
    await message.answer("Здесь будет список учеников и PDF с их успеваемостью.")
