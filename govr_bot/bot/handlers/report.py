from aiogram import Router, types
from aiogram.types import FSInputFile
from aiogram.filters import Command

from bot.services.spreadsheet import fetch_user_records
from bot.services.pdf_generator import make_report

router = Router()

@router.message(lambda m: m.text == "📄 Получить отчёт")
@router.message(Command("report"))
async def btn_report(m: types.Message):
    records = fetch_user_records(m.from_user.id)
    if not records:
        return await m.answer("Ты ещё не сдал ни одной темы.")
    pdf_path = make_report(m.from_user.id, m.from_user.full_name, records)
    await m.answer_document(FSInputFile(pdf_path))
