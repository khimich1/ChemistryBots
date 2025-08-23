from aiogram import Router, types
from aiogram.types import FSInputFile
from aiogram.filters import Command



from bot.services.spreadsheet import fetch_user_records
from bot.services.pdf_generator import make_report

# Импортируем модуль для генерации имен файлов
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "parent_bot", "bot", "services"))
from filename_generator import get_filename_for_user

router = Router()

@router.message(lambda m: m.text == "📄 Получить отчёт")
@router.message(Command("report"))
async def btn_report(m: types.Message):
    records = fetch_user_records(m.from_user.id)
    if not records:
        return await m.answer("Ты ещё не сдал ни одной темы.")
    
    # Генерируем имя файла с именем ученика и датой
    filename = get_filename_for_user(
        m.from_user.id, 
        m.from_user.full_name, 
        m.from_user.username
    )
    
    # Получаем отображаемое имя для передачи в make_report
    display_name = get_filename_for_user(
        m.from_user.id, 
        m.from_user.full_name, 
        m.from_user.username
    ).replace('.pdf', '').replace('_23.08.2025', '')  # Убираем расширение и дату
    
    pdf_path = make_report(m.from_user.id, display_name, records, filename)
    await m.answer_document(FSInputFile(pdf_path))
