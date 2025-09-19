from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters.callback_data import CallbackData

from bot.utils import user_learning_state
from bot.utils_pkg.message_manager import message_manager
from bot.services.spreadsheet import fetch_user_records
from bot.services.answer_db import (
    get_user_full_name,
    set_user_full_name,
    get_random_motivation_text,
    get_user_activity_stats,
    log_start_param,
    mark_subscribed,
)
from bot.services.pdf_generator import make_report
from bot.services.subscription import is_user_subscribed, build_subscribe_kb
from bot.services.task_solver import process_image_for_task_or_conspect, solve_text_task, is_chemistry_task
from io import BytesIO

# если main_kb используется в других файлах — импортируй там: from bot.handlers.menu import main_kb

router = Router()

# Callback data для кнопок решатора
class TaskSolverCallback(CallbackData, prefix="task_solver"):
    action: str

class ProfileStates(StatesGroup):
    waiting_full_name = State()

class TaskSolverStates(StatesGroup):
    waiting_photo = State()

# ==== Клавиатура для решатора задач ====
def get_task_solver_kb():
    """Создает inline клавиатуру с кнопками для решатора задач"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 В главное меню",
                    callback_data=TaskSolverCallback(action="main_menu").pack()
                ),
                InlineKeyboardButton(
                    text="📝 Еще задание",
                    callback_data=TaskSolverCallback(action="another_task").pack()
                )
            ]
        ]
    )

# ==== Главное меню (обновлено) ====
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Теория по химии"), KeyboardButton(text="📝 Тесты")],
        [KeyboardButton(text="🔬 Решатор задач"), KeyboardButton(text="🃏 Карточки для запоминания")],
        [KeyboardButton(text="📈 Получить отчёт"), KeyboardButton(text="ℹ️ Как работает бот")],
        [KeyboardButton(text="💳 Тарифы и оплата"), KeyboardButton(text="📞 Бесплатное занятие")],
    ],
    resize_keyboard=True
)

# ==== /start и возврат в меню ====
@router.message(lambda m: (
    (m.text or "").strip().lower() in {"/start", "/menu", "меню", "в меню", "в главное меню", "⬅️ в меню"}
    or (m.text or "").strip() == "🏠 В главное меню"
    or ("меню" in (m.text or "").lower())
))
async def cmd_start(m: types.Message, state: FSMContext):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    # Очищаем все состояния при возврате в меню
    await state.clear()
    
    # Очищаем состояние карточек
    try:
        from bot.handlers.flashcards import user_flashcards_state
        user_id = m.from_user.id
        if user_id in user_flashcards_state:
            user_flashcards_state[user_id] = {}
    except Exception:
        pass
    
    # Логируем метку источника из /start <param>
    try:
        text = (m.text or "").strip()
        parts = text.split(maxsplit=1)
        start_param = parts[1] if len(parts) == 2 and parts[0].lower().startswith("/start") else None
        log_start_param(m.from_user.id, getattr(m.from_user, "username", None), start_param)
    except Exception:
        pass
    # Сначала проверим подписку
    subscription_status = await is_user_subscribed(m.bot, m.from_user.id)
    
    if subscription_status is None:
        # Ошибка API — показываем понятное сообщение, но всё равно предлагаем подписаться
        msg = await m.answer(
            "Не удалось проверить подписку (временная ошибка). Попробуйте позже или нажмите 'Проверить подписку' ещё раз.",
            reply_markup=build_subscribe_kb()
        )
        message_manager.add_message(m.from_user.id, msg.message_id)
        return
    elif not subscription_status:
        # Пользователь не подписан
        msg = await m.answer(
            "Чтобы пользоваться ботом, подпишись на канал и нажми 'Проверить подписку'.",
            reply_markup=build_subscribe_kb()
        )
        message_manager.add_message(m.from_user.id, msg.message_id)
        return
    full_name = get_user_full_name(m.from_user.id)
    if not full_name:
        await state.set_state(ProfileStates.waiting_full_name)
        msg = await m.answer(
            "Пожалуйста, напиши своё имя и фамилию в одном сообщении (например: Иван Петров).\n"
            "Это нужно для отчётов и статистики."
        )
        message_manager.add_message(m.from_user.id, msg.message_id)
        return

    # Отправим мотивационное сообщение (если таблица chem_motivation есть в базе)
    mot = get_random_motivation_text()
    if mot:
        try:
            sent = await m.answer(mot)
            try:
                message_manager.add_message(m.from_user.id, sent.message_id)
            except Exception:
                pass
        except Exception:
            pass

    # Мотивация и статистика активности
    streak, last7 = get_user_activity_stats(m.from_user.id)
    mot = get_random_motivation_text()
    extra_lines: list[str] = []
    if streak and streak > 1:
        extra_lines.append(f"Ты шёл к своей цели {streak} дн. подряд. Не останавливайся!")
    if last7:
        extra_lines.append(f"Активных дней за 7 дней: {last7}.")
    if mot:
        extra_lines.append(mot)

    sent = await m.answer(
        "👋 Привет! Я твой персональный помощник по химии.\n\n"
        "🎯 <b>Что я умею:</b>\n"
        "• 📚 <b>Теория по химии</b> — структурированные уроки по всем разделам\n"
        "• 🔬 <b>Решатор задач</b> — ИИ поможет с любыми заданиями\n"
        "• 📝 <b>Тесты</b> — тренировка с мгновенной проверкой и объяснениями\n"
        "• 📈 <b>Отчёты</b> — аналитика твоего прогресса\n"
        "• 🃏 <b>Карточки</b> — запоминание формул и названий\n\n"
        "💡 <b>Совет:</b> Начни с теории, потом закрепляй тестами. Каждый день понемногу — и результат не заставит себя ждать!"
        + ("\n\n" + "\n".join(extra_lines) if extra_lines else ""),
        reply_markup=main_kb,
        parse_mode="HTML"
    )
    message_manager.add_message(m.from_user.id, sent.message_id)

@router.callback_query(lambda c: c.data == "check_sub")
async def on_check_subscription(cb: types.CallbackQuery, state: FSMContext):
    # Повторная проверка подписки по кнопке
    subscription_status = await is_user_subscribed(cb.bot, cb.from_user.id)
    
    if subscription_status is None:
        # Ошибка API — показываем понятное сообщение
        await cb.answer("Не удалось проверить подписку (временная ошибка). Попробуйте позже.", show_alert=True)
        try:
            sent = await cb.message.answer(
                "Не удалось проверить подписку (временная ошибка). Попробуйте позже или нажмите 'Проверить подписку' ещё раз.",
                reply_markup=build_subscribe_kb()
            )
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass
    elif subscription_status:
        # Пользователь подписан
        try:
            mark_subscribed(cb.from_user.id)
        except Exception:
            pass
        # Удалим сообщение с кнопками, если возможно
        try:
            await cb.message.delete()
        except Exception:
            pass

        full_name = get_user_full_name(cb.from_user.id)
        if not full_name:
            await state.set_state(ProfileStates.waiting_full_name)
            msg = await cb.message.answer(
                "Пожалуйста, напиши своё имя и фамилию в одном сообщении (например: Иван Петров).\n"
                "Это нужно для отчётов и статистики."
            )
            message_manager.add_message(cb.from_user.id, msg.message_id)
        else:
            # Очищаем все состояния при возврате в меню
            await state.clear()
            await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
            sent = await cb.message.answer("Спасибо за подписку! Ниже — главное меню.", reply_markup=main_kb)
            message_manager.add_message(cb.from_user.id, sent.message_id)
        await cb.answer("Подписка подтверждена ✅", show_alert=False)
    else:
        # Пользователь не подписан
        await cb.answer("Ещё не вижу подписки. Подпишись и попробуй снова.", show_alert=True)
        try:
            sent = await cb.message.answer(
                "Подписка всё ещё не подтверждена. Нажми ещё раз 'Проверить подписку' после подписки.",
                reply_markup=build_subscribe_kb(),
            )
            message_manager.add_message(cb.from_user.id, sent.message_id)
        except Exception:
            pass

@router.message(ProfileStates.waiting_full_name)
async def set_full_name(m: types.Message, state: FSMContext):
    text = (m.text or "").strip()
    # Простая валидация: хотя бы два слова
    parts = [p for p in text.replace("  ", " ").split(" ") if p]
    if len(parts) < 2:
        await m.answer("Похоже, это не имя и фамилия. Напиши, пожалуйста, имя и фамилию, например: Мария Иванова")
        return
    full_name = " ".join(parts[:3])  # на всякий — первые 2-3 слова
    set_user_full_name(m.from_user.id, getattr(m.from_user, "username", None), full_name)
    await state.clear()
    # Возврат в меню с мотивацией
    mot = get_random_motivation_text()
    if mot:
        try:
            sent = await m.answer(mot)
            try:
                message_manager.add_message(m.from_user.id, sent.message_id)
            except Exception:
                pass
        except Exception:
            pass

    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    sent = await m.answer("Ниже — главное меню.", reply_markup=main_kb)
    message_manager.add_message(m.from_user.id, sent.message_id)

# ==== Подменю «Теория по химии» ====
@router.message(lambda m: (m.text or "").strip().lower() in {
    "📚 теория по химии",
    "курс по химии",
    "курс",
    "теория",
})
async def theory_menu(m: types.Message):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    theory_description = """**Теория по химии**

**Что ты получишь:**
• Структурированные лекции по всем разделам химии
• Интерактивные вопросы после каждого блока
• Голосовые объяснения сложных тем
• Отслеживание прогресса изучения
• Возможность задавать вопросы ИИ

**Как работает обучение:**
1. Выбираешь раздел и главу
2. Читаешь теорию небольшими порциями
3. Отвечаешь на вопросы для закрепления
4. Задаёшь вопросы ИИ при необходимости
5. Отслеживаешь свой прогресс

**Идеально для:** систематического изучения химии с нуля до продвинутого уровня"""
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Начала химии")],
            [KeyboardButton(text="⚗️ Химия элементов")],
            [KeyboardButton(text="🧬 Органическая химия")],
            [KeyboardButton(text="⬅️ В меню")],
        ],
        resize_keyboard=True
    )
    msg = await m.answer(theory_description, reply_markup=kb, parse_mode="Markdown")
    message_manager.add_message(m.from_user.id, msg.message_id)




# ==== Подменю «Тесты» из главного меню ====
@router.message(lambda m: (m.text or "").strip().lower() == "📝 тесты")
async def tests_entry_menu(m: types.Message):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    # Завершаем активную сессию теории, если была
    try:
        from bot.handlers.topics import user_learning_state
        user_learning_state.pop(m.from_user.id, None)
    except Exception:
        pass
    from bot.handlers.tests import tests_instruction_text
    msg1 = await m.answer(tests_instruction_text(), parse_mode="HTML")
    message_manager.add_message(m.from_user.id, msg1.message_id)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧪 Тестовая часть ЕГЭ по химии")],
            [KeyboardButton(text="🧪 Тестовая часть ОГЭ по химии")],
            [KeyboardButton(text="⬅️ В меню")],
        ],
        resize_keyboard=True
    )
    msg2 = await m.answer("Выбери раздел тестов:", reply_markup=kb)
    message_manager.add_message(m.from_user.id, msg2.message_id)

@router.message(lambda m: (m.text or "").strip().lower() == "🧪 тестовая часть егэ по химии")
async def tests_open_catalog(m: types.Message):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    # На всякий случай тоже завершим теорию
    try:
        from bot.handlers.topics import user_learning_state
        user_learning_state.pop(m.from_user.id, None)
    except Exception:
        pass
    from bot.handlers.tests import get_tests_types_kb
    kb = get_tests_types_kb(with_menu=True, include_back=True)
    msg = await m.answer("Выбери тест:", reply_markup=kb)
    message_manager.add_message(m.from_user.id, msg.message_id)

@router.callback_query(lambda c: c.data == "tests_go_back")
async def tests_go_back(cb: types.CallbackQuery):
    await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    # Удаляем сообщение со списком тестов
    try:
        await cb.message.delete()
    except Exception:
        # если не удалилось — просто продолжим и перешлём меню ниже
        pass
    # Возврат к подменю тестов (кнопки Reply)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧪 Тестовая часть ЕГЭ по химии")],
            [KeyboardButton(text="🧪 Тестовая часть ОГЭ по химии")],
            [KeyboardButton(text="⬅️ В меню")],
        ],
        resize_keyboard=True
    )
    sent = await cb.message.answer("Выбери раздел тестов:", reply_markup=kb)
    message_manager.add_message(cb.from_user.id, sent.message_id)
    await cb.answer()

# Универсальная кнопка «В главное меню» для инлайн-кнопок
@router.callback_query(lambda c: c.data == "to_main_menu")
async def to_main_menu_cb(cb: types.CallbackQuery):
    await message_manager.delete_user_messages_fast(cb.message.bot, cb.from_user.id, cb.message.chat.id)
    # Удаляем последнее сообщение и ещё 4 предыдущих (всего до 5)
    try:
        base = cb.message.message_id
        for delta in range(0, 5):
            try:
                await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=base - delta)
            except Exception:
                pass
    except Exception:
        pass
    sent = await cb.message.answer("Главное меню:", reply_markup=main_kb)
    message_manager.add_message(cb.from_user.id, sent.message_id)
    await cb.answer()

# ==== Отчёт (PDF) ====
@router.message(lambda m: m.text == "📈 Получить отчёт")
@router.message(Command("report"))
async def get_report(m: types.Message):
    # Лимит 1 PDF/месяц для бесплатного тарифа
    try:
        from bot.services.plan import get_user_plan_code, limits_for, consume_monthly
        plan = get_user_plan_code(m.from_user.id)
        limit = limits_for(plan)["reports_per_month"]
        ok, _left = consume_monthly(m.from_user.id, "report", limit)
        if not ok:
            msg = await m.answer("В бесплатном тарифе — 1 PDF-отчёт в месяц. Оформи подписку в ‘💳 Тарифы и оплата’.")
            message_manager.add_message(m.from_user.id, msg.message_id)
            return
    except Exception:
        pass

    records = fetch_user_records(m.from_user.id)
    if not records:
        msg = await m.answer("Пока нет данных для отчёта — пройди темы или тесты.")
        message_manager.add_message(m.from_user.id, msg.message_id)
        return
    pdf_path = make_report(m.from_user.id, m.from_user.full_name, records)
    await m.answer_document(FSInputFile(pdf_path), caption="Вот твой PDF-отчёт!")

# ==== Справка ====
@router.message(lambda m: m.text == "ℹ️ Как работает бот")
async def how_bot_works(m: types.Message):
    text = (
        "🎓 <b>Как эффективно пользоваться ботом</b>\n\n"
        "🚀 <b>Рекомендуемый план обучения:</b>\n"
        "1️⃣ Изучай теорию по разделам\n"
        "2️⃣ Закрепляй тестами\n"
        "3️⃣ Решай сложные задачи\n"
        "4️⃣ Отслеживай прогресс\n\n"
        "📚 <b>Теория по химии:</b>\n"
        "• <b>Начала химии</b> — основы для всех\n"
        "• <b>Химия элементов</b> — неорганическая химия\n"
        "• <b>Органическая химия</b> — соединения углерода\n\n"
        "🎯 <b>Как изучать теорию:</b>\n"
        "• Цветные индикаторы показывают твой прогресс: 🟩 отлично, 🟨 хорошо, 🟥 удовлетворительно\n"
        "• Используй аудио для лучшего запоминания\n"
        "• Задавай вопросы ИИ — он объяснит непонятное\n"
        "• Выполняй задания после каждого раздела\n\n"
        "📝 <b>Тесты — твоя тренировка:</b>\n"
        "• 30 заданий в каждом тесте\n"
        "• Мгновенная проверка с объяснениями\n"
        "• Подсказки, если застрял\n"
        "• Работа над ошибками — повторяй только то, что не получается\n\n"
        "🔬 <b>Решатор задач:</b>\n"
        "• Присылай текст или фото любой химической задачи\n"
        "• ИИ даст подробное решение с объяснением\n"
        "• Можно распознавать конспекты и оформлять их красиво\n\n"
        "📈 <b>Отслеживание прогресса:</b>\n"
        "• PDF-отчёты с детальной статистикой\n"
        "• Видишь, какие темы знаешь хорошо, а какие нужно подтянуть\n"
        "• Мотивация через достижения и рекорды\n\n"
        "💡 <b>Полезные команды:</b>\n"
        "/start — начать обучение\n"
        "/menu — главное меню\n"
        "/resume — продолжить с того места, где остановился\n"
        "/tests — сразу к тестам\n"
        "/report — получить отчёт\n\n"
        "🎯 <b>Совет:</b> Занимайся регулярно, даже по 15-20 минут в день. "
        "Лучше немного, но каждый день, чем много, но редко!"
    )
    
    # Создаём inline клавиатуру с кнопкой "Назад"
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_from_instructions")]
        ]
    )
    
    msg = await m.answer(text, reply_markup=back_kb, parse_mode="HTML")
    message_manager.add_message(m.from_user.id, msg.message_id)

# Дублируем справку на команду /help
@router.message(Command("help"))
async def help_cmd(m: types.Message):
    await how_bot_works(m)

# ==== (опционально) Возобновление курса, если где-то используется ====
@router.message(lambda m: m.text == "▶️ Продолжить")
async def resume_course(m: types.Message):
    state = user_learning_state.get(m.from_user.id)
    if not state:
        await m.answer("Ты ещё не начинал обучение. Открой «📚 Теория по химии» и выбери раздел.", reply_markup=main_kb)
        return
    # Если состояние есть — показываем следующий chunk
    from bot.handlers.topics import send_next_chunk
    await send_next_chunk(m.from_user.id, m.bot)

# ==== Решатор задач ====
@router.message(lambda m: m.text == "🔬 Решатор задач")
async def ask_for_task_or_conspect_photo(m: types.Message, state: FSMContext):
    await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
    await state.set_state(TaskSolverStates.waiting_photo)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ В меню")]],
        resize_keyboard=True
    )
    
    # Получаем информацию о тарифе и запросах
    from bot.services.plan import get_user_plan_code, get_plan_name, get_task_solver_remaining
    plan_code = get_user_plan_code(m.from_user.id)
    plan_name = get_plan_name(plan_code)
    remaining, total = get_task_solver_remaining(m.from_user.id)
    
    msg_intro = await m.answer(
        f"🔬 <b>Решатор задач — твой ИИ-помощник</b>\n\n"
        f"💳 <b>Ваш тариф:</b> {plan_name}\n"
        f"📊 <b>Запросов в месяц:</b> {remaining}/{total}\n\n"
        "🎯 <b>Что я умею:</b>\n"
        "• 📝 <b>Решать любые химические задачи</b> — от простых до олимпиадных\n"
        "• 📸 <b>Распознавать задачи с фото</b> — просто сфотографируй задание\n"
        "• 📋 <b>Оформлять конспекты</b> — превращу твои записи в красивый текст\n"
        "• 🧠 <b>Объяснять решения</b> — не просто ответ, а понимание процесса\n\n"
        "💡 <b>Как использовать:</b>\n"
        "1️⃣ Пришли текст задачи или сфотографируй её\n"
        "2️⃣ Получи подробное решение с объяснением\n"
        "3️⃣ Разберись в логике решения\n"
        "4️⃣ Задай уточняющие вопросы, если что-то непонятно\n\n"
        "🚀 <b>Совет:</b> Не просто списывай ответы! Изучай ход решения, "
        "задавай вопросы ИИ о непонятных моментах. Это поможет тебе научиться решать подобные задачи самостоятельно.\n\n"
        "⚠️ <b>Важно:</b> Я не изменяю условия задач и не добавляю лишнего — работаю только с тем, что ты присылаешь.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    try:
        message_manager.add_message(m.from_user.id, msg_intro.message_id)
    except Exception:
        pass


@router.message(TaskSolverStates.waiting_photo)
async def handle_task_or_conspect_input(m: types.Message, state: FSMContext):
    # Возможность выйти в меню
    if (m.text or "").lower().strip() in {"⬅️ в меню", "в меню", "/menu"}:
        await state.clear()
        try:
            await message_manager.delete_user_messages_fast(m.bot, m.from_user.id, m.chat.id)
        except Exception:
            pass
        menu_msg = await m.answer("Возвращаю в меню.", reply_markup=main_kb)
        try:
            message_manager.add_message(m.from_user.id, menu_msg.message_id)
        except Exception:
            pass
        return

    # Обработка текстового сообщения
    if m.text:
        # Проверяем лимит запросов
        from bot.services.plan import get_user_plan_code, limits_for, consume_monthly
        plan = get_user_plan_code(m.from_user.id)
        limits = limits_for(plan)
        limit = limits["task_solver_per_month"]
        
        ok, remaining = consume_monthly(m.from_user.id, "task_solver", limit)
        if not ok:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Тарифы и оплата", callback_data="to_tariffs")]
            ])
            await m.answer(
                "❌ Лимит запросов к решатору задач на этот месяц исчерпан!\n\n"
                "💳 Оформите подписку для увеличения лимита:\n"
                "• Бесплатный тариф: 20 запросов/месяц\n"
                "• Платные тарифы: 100 запросов/месяц",
                reply_markup=kb
            )
            await state.clear()
            return
        
        tmp = await m.answer("🔎 Анализирую текст… Подождите пару секунд")
        try:
            message_manager.add_message(m.from_user.id, tmp.message_id)
        except Exception:
            pass
        try:
            # Проверяем, является ли текст химической задачей
            is_task = await is_chemistry_task(m.text)

            if is_task:
                solution = await solve_text_task(m.text)
                if solution:
                    res = await m.answer(
                        f"📝 Решение задачи:\n\n{solution}\n\n📊 Осталось запросов: {remaining}",
                        reply_markup=get_task_solver_kb()
                    )
                    try:
                        message_manager.add_message(m.from_user.id, res.message_id)
                    except Exception:
                        pass
                else:
                    err = await m.answer("Не удалось решить задачу. Попробуйте сформулировать её более чётко.")
                    try:
                        message_manager.add_message(m.from_user.id, err.message_id)
                    except Exception:
                        pass
            else:
                notask = await m.answer(
                    "🔍 Это не похоже на химическую задачу.\n\n"
                    "Отправьте:\n"
                    "• 📝 Текст химической задачи — получите решение с объяснениями\n"
                    "• 📸 Фото химической задачи — получите решение с объяснениями\n"
                    "• 📸 Фото конспекта — получите аккуратно оформленный текст\n\n"
                    "⚠️ Важно: в заданиях и конспектах категорически нельзя ничего менять или добавлять!"
                )
                try:
                    message_manager.add_message(m.from_user.id, notask.message_id)
                except Exception:
                    pass
        except Exception:
            e_msg = await m.answer("Произошла ошибка при обработке текста. Попробуйте ещё раз позже.")
            try:
                message_manager.add_message(m.from_user.id, e_msg.message_id)
            except Exception:
                pass
        finally:
            await state.clear()
        return

    # Обработка фото
    if getattr(m, "photo", None):
        # Проверяем лимит запросов
        from bot.services.plan import get_user_plan_code, limits_for, consume_monthly
        plan = get_user_plan_code(m.from_user.id)
        limits = limits_for(plan)
        limit = limits["task_solver_per_month"]
        
        ok, remaining = consume_monthly(m.from_user.id, "task_solver", limit)
        if not ok:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Тарифы и оплата", callback_data="to_tariffs")]
            ])
            await m.answer(
                "❌ Лимит запросов к решатору задач на этот месяц исчерпан!\n\n"
                "💳 Оформите подписку для увеличения лимита:\n"
                "• Бесплатный тариф: 20 запросов/месяц\n"
                "• Платные тарифы: 100 запросов/месяц",
                reply_markup=kb
            )
            await state.clear()
            return
        
        tmp = await m.answer("🔎 Анализирую фото… Подождите пару секунд")
        try:
            message_manager.add_message(m.from_user.id, tmp.message_id)
        except Exception:
            pass
        try:
            # Берём самое большое превью и скачиваем через встроенный клиент aiogram
            file = await m.bot.get_file(m.photo[-1].file_id)
            buffer = BytesIO()
            await m.bot.download(file, destination=buffer)
            img_bytes = buffer.getvalue()

            content_type, result = await process_image_for_task_or_conspect(img_bytes)
            
            if content_type == "НЕ_ОПРЕДЕЛЕНО":
                msg = await m.answer(result)
                try:
                    message_manager.add_message(m.from_user.id, msg.message_id)
                except Exception:
                    pass
            elif not result:
                msg = await m.answer("Не удалось обработать фото. Попробуйте сделать снимок чётче и без бликов.")
                try:
                    message_manager.add_message(m.from_user.id, msg.message_id)
                except Exception:
                    pass
            else:
                # Добавляем заголовок в зависимости от типа контента
                if content_type == "ЗАДАЧА":
                    header = f"📝 Решение задачи:\n\n{result}\n\n📊 Осталось запросов: {remaining}"
                    msg = await m.answer(header, reply_markup=get_task_solver_kb())
                    try:
                        message_manager.add_message(m.from_user.id, msg.message_id)
                    except Exception:
                        pass
                else:  # КОНСПЕКТ
                    header = f"📸 Распознанный конспект:\n\n{result}\n\n📊 Осталось запросов: {remaining}"
                    msg = await m.answer(header, reply_markup=get_task_solver_kb())
                    try:
                        message_manager.add_message(m.from_user.id, msg.message_id)
                    except Exception:
                        pass
        except Exception as e:
            msg = await m.answer("Произошла ошибка при обработке фото. Попробуйте ещё раз позже.")
            try:
                message_manager.add_message(m.from_user.id, msg.message_id)
            except Exception:
                pass
        finally:
            await state.clear()
        return

    # Если отправлено что-то другое
    msg = await m.answer("Пожалуйста, отправьте текст химической задачи или фото задачи/конспекта 📝📷")
    try:
        message_manager.add_message(m.from_user.id, msg.message_id)
    except Exception:
        pass
    await state.clear()

# ==== Обработчики callback кнопок решатора ====
@router.callback_query(TaskSolverCallback.filter())
async def handle_task_solver_callback(callback: types.CallbackQuery, callback_data: TaskSolverCallback, state: FSMContext):
    await callback.answer()  # Убираем "часики" у кнопки
    
    if callback_data.action == "main_menu":
        # Возвращаемся в главное меню
        await state.clear()
        try:
            await message_manager.delete_user_messages(callback.message.bot, callback.from_user.id, callback.message.chat.id)
        except Exception:
            pass
        back_msg = await callback.message.answer("Возвращаю в главное меню.", reply_markup=main_kb)
        try:
            message_manager.add_message(callback.from_user.id, back_msg.message_id)
        except Exception:
            pass
        # Удаляем сообщение с кнопками
        try:
            await callback.message.delete()
        except:
            pass
    
    elif callback_data.action == "another_task":
        # Удаляем 3 последних сообщения (включая текущее)
        try:
            # Удаляем текущее сообщение с кнопками
            await callback.message.delete()
            
            # Удаляем еще 2 предыдущих сообщения
            chat_id = callback.message.chat.id
            message_id = callback.message.message_id
            
            for i in range(1, 3):  # Удаляем 2 предыдущих сообщения
                try:
                    await callback.bot.delete_message(chat_id, message_id - i)
                except:
                    pass  # Игнорируем ошибки, если сообщение уже удалено
                    
        except Exception as e:
            # Если не удалось удалить, просто отправляем новое сообщение
            pass
        
        # Отправляем сообщение для нового задания
        msg = await callback.message.answer(
            "📝 Отправьте новую химическую задачу (текстом или фото):",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="⬅️ В меню")]],
                resize_keyboard=True
            )
        )
        try:
            message_manager.add_message(callback.from_user.id, msg.message_id)
        except Exception:
            pass
        await state.set_state(TaskSolverStates.waiting_photo)

# ==== Обработчик кнопки "Назад" из инструкций ====
@router.callback_query(lambda c: c.data == "back_from_instructions")
async def back_from_instructions(cb: CallbackQuery):
    """Удаляет все сообщения и показывает главное меню"""
    # Очищаем все сообщения пользователя
    await message_manager.delete_user_messages(cb.bot, cb.from_user.id, cb.message.chat.id)
    
    # Отправляем главное меню
    sent = await cb.bot.send_message(
        chat_id=cb.message.chat.id,
        text="Главное меню:",
        reply_markup=main_kb
    )
    message_manager.add_message(cb.from_user.id, sent.message_id)
    await cb.answer()

# ==== Обработчик кнопки розыгрыша ====
# @router.message(lambda m: (m.text or "").strip() == "🎁 Розыгрыш")  # Розыгрыш - закомментировано
# async def giveaway_button_handler(m: types.Message):
#     """Обработчик кнопки розыгрыша в главном меню"""
#     from bot.handlers.giveaway import register_for_giveaway
#     await register_for_giveaway(m)
