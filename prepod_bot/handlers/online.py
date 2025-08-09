from aiogram import Router, types
from services.students import get_online_students

router = Router()

@router.message(lambda message: "Ученики онлайн" in message.text)
async def show_online(message: types.Message):
    print(f"[LOG] Вызвана команда 'Ученики онлайн': '{message.text}'")
    students = get_online_students()
    print(f"[LOG] Возвращено студентов онлайн: {len(students)} — {students}")

    if not students:
        await message.answer("Нет учеников онлайн в данный момент.")
        print("[LOG] Никого онлайн не найдено")
        return

    text = "Ученики онлайн:\n\n"
    for student in students:
        text += (
            f"ID ученика: {student['user_id']}\n"
            f"Время активности: {student['started_at']}\n"
            f"/history_{student['user_id']}\n\n"
        )
    await message.answer(text)
    print("[LOG] Сообщение с учениками онлайн отправлено!")
