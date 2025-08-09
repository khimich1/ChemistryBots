import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# === ВАЖНО! ЯВНЫЙ ПУТЬ К БАЗЕ ДАННЫХ ===
ANSWERS_DB = r"C:\Users\Роман\Desktop\govr_bot\test_answers.db"
QUESTIONS_DB = r"C:\Users\Роман\Desktop\govr_bot\bot\tests1.db"

print("Используется база ответов:", ANSWERS_DB)
print("Используется база вопросов:", QUESTIONS_DB)
if not os.path.exists(ANSWERS_DB):
    print("ВНИМАНИЕ: test_answers.db НЕ НАЙДЕН!")
if not os.path.exists(QUESTIONS_DB):
    print("ВНИМАНИЕ: tests1.db НЕ НАЙДЕН!")

API_TOKEN = "8117876783:AAHq-vAAiVPYawV3Mxx3j1Lt6x3f-9tagoQ"  # Лучше вынести в .env!
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

def get_username(user_id):
    conn = sqlite3.connect(ANSWERS_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT username FROM test_answers WHERE user_id=? AND username IS NOT NULL AND username != '' ORDER BY id DESC LIMIT 1",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    return str(user_id)

def get_question_text_and_answer(question_id, test_type=None):
    conn = sqlite3.connect(QUESTIONS_DB)
    cur = conn.cursor()
    if test_type is not None:
        cur.execute(
            "SELECT question, correct_answer FROM tests WHERE id=? AND type=? LIMIT 1",
            (question_id, test_type)
        )
        row = cur.fetchone()
        if row:
            conn.close()
            return row[0], row[1]
    cur.execute(
        "SELECT question, correct_answer FROM tests WHERE id=? LIMIT 1",
        (question_id,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return "—", "—"

# ====== ДОБАВЛЕНА ФУНКЦИЯ для вариантов ======
def get_question_options(question_id, test_type=None):
    conn = sqlite3.connect(QUESTIONS_DB)
    cur = conn.cursor()
    if test_type is not None:
        cur.execute(
            "SELECT options FROM tests WHERE id=? AND type=? LIMIT 1",
            (question_id, test_type)
        )
        row = cur.fetchone()
        if row and row[0]:
            conn.close()
            return row[0]
    cur.execute(
        "SELECT options FROM tests WHERE id=? LIMIT 1",
        (question_id,)
    )
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    return ""

def get_question_number_in_test(question_id, test_type):
    conn = sqlite3.connect(QUESTIONS_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM tests WHERE type=? ORDER BY id ASC",
        (test_type,)
    )
    all_ids = [row[0] for row in cur.fetchall()]
    conn.close()
    if question_id in all_ids:
        number = all_ids.index(question_id) + 1
        total = len(all_ids)
        return number, total
    return None, None

def get_active_students(timeout_minutes=30):
    conn = sqlite3.connect(ANSWERS_DB)
    cur = conn.cursor()
    # Берём только тех, кто начал задание менее X минут назад
    cur.execute("""
        SELECT user_id, test_type, question_id, started_at
        FROM test_activity
        WHERE answered_at IS NULL
    """)
    result = []
    now = datetime.now()
    for user_id, test_type, question_id, started_at in cur.fetchall():
        if started_at:
            try:
                t1 = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                delta = now - t1
                if delta.total_seconds() < timeout_minutes * 60:
                    result.append((user_id, test_type, question_id, started_at))
            except Exception as e:
                # Если не получилось преобразовать дату — игнорируем запись
                pass
    conn.close()
    return result


# == 1. /online выводим КНОПКИ-УЧЕНИКИ ==
@dp.message(Command("online"))
async def online_command(message: types.Message):
    users = get_active_students()
    if not users:
        await message.answer("Сейчас никто не решает задания.")
        return
    lines = ["🟢 <b>Ученики онлайн (решают задания):</b>"]
    already = set()
    for user_id, test_type, question_id, started_at in users:
        if user_id in already:
            continue
        already.add(user_id)
        username = get_username(user_id)
        number, total = get_question_number_in_test(question_id, test_type)
        question_text, correct_ans = get_question_text_and_answer(question_id, test_type)
        question_options = get_question_options(question_id, test_type)
        # Считаем время
        if started_at:
            try:
                t1 = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                delta = now - t1
                min_, sec_ = divmod(delta.seconds, 60)
                time_str = f"{min_} мин {sec_} сек"
            except:
                time_str = "?"
        else:
            time_str = "нет данных"
        # Формируем корректно строку вопроса
        if number and total:
            question_info = f"Вопрос: {number} из {total} (id={question_id})"
        else:
            question_info = f"Вопрос id={question_id}"
        # Собираем всё вместе
        lines.append(
            f"👤 <b>{username}</b>\n"
            f"{question_info}\n"
            f"{question_text}\n"
            f"{'Варианты ответа:\n' + question_options if question_options else ''}\n"
            f"<i>Время на задании: <b>{time_str}</b></i>\n"
            "———"
        )
    # Сообщения не должны быть слишком длинными
    MAX_LEN = 4096
    text = "\n\n".join(lines)
    for i in range(0, len(text), MAX_LEN):
        await message.answer(text[i:i+MAX_LEN], parse_mode="HTML")

# == 2. После клика на ученика — КНОПКИ-ТЕСТЫ с статистикой ==
@dp.callback_query(lambda call: call.data.startswith("show_"))
async def show_student_topics(call: CallbackQuery):
    user_id = int(call.data.split("_")[1])
    username = get_username(user_id)
    conn = sqlite3.connect(ANSWERS_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT test_type,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) as correct,
               SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END) as wrong
        FROM test_activity
        WHERE user_id=?
        GROUP BY test_type
        ORDER BY test_type
    """, (user_id,))
    types_stats = cur.fetchall()
    conn.close()
    if not types_stats:
        await call.message.answer(f"У ученика {username} нет решённых заданий.")
        return
    topics = []
    for test_type, total, correct, wrong in types_stats:
        topic_name = f"Тест {test_type}"
        topics.append((test_type, topic_name, total, correct or 0, wrong or 0))
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{topic_name} (решено: {total}, правильно: {correct}, ошибок: {wrong})",
                callback_data=f"topic_{user_id}_{test_type}"
            )
        ]
        for test_type, topic_name, total, correct, wrong in topics
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.answer(
        f"🧑 <b>{username}</b>\nВыбери тест, чтобы посмотреть ответы:",
        parse_mode="HTML",
        reply_markup=kb
    )

# == 3. После клика на тест — показываем ответы по этому тесту ==
@dp.callback_query(lambda call: call.data.startswith("topic_"))
async def show_student_answers_by_topic(call: CallbackQuery):
    parts = call.data.split("_")
    user_id = int(parts[1])
    test_type = int(parts[2])
    username = get_username(user_id)
    topic_name = f"Тест {test_type}"
    conn = sqlite3.connect(ANSWERS_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT question_id, is_correct, started_at, answered_at
        FROM test_activity
        WHERE user_id=? AND test_type=?
        ORDER BY answered_at DESC, started_at DESC
        LIMIT 100
    """, (user_id, test_type))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await call.message.answer(f"По теме <b>{topic_name}</b> ученик {username} ещё не решал задания.")
        return
    lines = [f"🧑 <b>{username}</b> — {topic_name}"]
    for question_id, is_correct, started_at, answered_at in rows:
        number, total = get_question_number_in_test(question_id, test_type)
        if is_correct == 1:
            status = "✅"
        elif is_correct == 0:
            status = "❌"
        else:
            status = "🟡"
        question_text, correct_ans = get_question_text_and_answer(question_id, test_type)

        # === ДОБАВЛЯЕМ ВАРИАНТЫ ОТВЕТОВ ===
        question_options = get_question_options(question_id, test_type)
        if question_options:
            options_str = f"\nВарианты ответа:\n{question_options}"
        else:
            options_str = ""

        if number and total:
            question_info = f"Вопрос: {number} из {total} (id={question_id})"
        else:
            question_info = f"Вопрос: {question_id}"
        time_str = ""
        if started_at and answered_at:
            try:
                t1 = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                t2 = datetime.strptime(answered_at, "%Y-%m-%d %H:%M:%S")
                delta = t2 - t1
                min_, sec_ = divmod(delta.seconds, 60)
                time_str = f"\nВремя на задание: <b>{min_} мин {sec_} сек</b>"
            except Exception as e:
                time_str = ""
        elif started_at and not answered_at:
            time_str = "\nВыполняет задание сейчас"
        lines.append(
            f"{status} {question_info}\n"
            f"Вопрос: {question_text}{options_str}\n"
            f"Правильный ответ: <b>{correct_ans}</b>{time_str}"
        )
    text = "\n\n".join(lines)
    MAX_LEN = 4096
    for i in range(0, len(text), MAX_LEN):
        await call.message.answer(text[i:i+MAX_LEN], parse_mode="HTML")

# == Главное меню (заглушка, если нужно) ==
@dp.callback_query(lambda call: call.data == "main_menu")
async def main_menu(call: CallbackQuery):
    await call.message.answer("Вы вернулись в главное меню.\n(Здесь может быть ваш контент или кнопки.)")

if __name__ == "__main__":
    print("Teacher assistant бот запущен!")
    import asyncio
    asyncio.run(dp.start_polling(bot))
