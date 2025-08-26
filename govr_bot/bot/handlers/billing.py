from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os, sqlite3

from bot.services.plan import get_user_plan_code, set_user_plan
from bot.services.billing import create_payment, check_payment, PRICES
from bot.services.answer_db import DB_FILE
from bot.services.teacher_access import is_student_approved_by_teacher


router = Router()


def get_tariff_description(plan_code: str) -> str:
	"""Возвращает продающее описание тарифа"""
	descriptions = {
		"group": """**Групповые занятия — 390 ₽/мес**

**Что включено:**
• Полный доступ ко всем функциям бота
• Неограниченные тесты по всем темам
• Безлимитные подсказки и объяснения
• Все блоки: "Начала химии", "Органика", "Элементы"
• Неограниченные вопросы к ИИ
• Безлимитные голосовые сообщения
• Полные карточки с объяснениями
• 5 отчётов в месяц

**Преимущества группового формата:**
• Экономия 600₽ в месяц по сравнению с самоподготовкой
• Поддержка преподавателя и группы
• Мотивация от других учеников
• Совместное решение сложных задач

**Идеально для:** учеников, которые хотят максимум за минимальную цену""",

		"self": """**Самоподготовка — 990 ₽/мес**

**Что включено:**
• Полный доступ ко всем функциям бота
• Неограниченные тесты по всем темам
• Безлимитные подсказки и объяснения
• Все блоки: "Начала химии", "Органика", "Элементы"
• Неограниченные вопросы к ИИ
• Безлимитные голосовые сообщения
• Полные карточки с объяснениями
• 5 отчётов в месяц

**Преимущества самоподготовки:**
• Полная свобода в обучении
• Гибкий график занятий
• Фокус на своих слабых местах
• Индивидуальный подход

**Идеально для:** самостоятельных учеников, которые хотят полный контроль над обучением""",

		"organic": """**Органическая химия — 2990 ₽**

**Что включено:**
• Полный доступ к блоку "Органика"
• Безлимитные тесты по органической химии
• Детальная практика по ошибкам
• Специальные карточки по органике
• Неограниченные подсказки и объяснения
• Голосовые объяснения сложных реакций
• Доступ на 31 день

**Почему органика:**
• Самая сложная часть химии
• Много практики и повторений
• Детальные объяснения механизмов
• Фокус на типичных ошибках

**Идеально для:** тех, кто хочет идеально знать органическую химию""",

		"elements": """**Химия элементов — 2990 ₽**

**Что включено:**
• Полный доступ к блоку "Элементы"
• Безлимитные тесты по неорганической химии
• Детальная практика по ошибкам
• Специальные карточки по элементам
• Неограниченные подсказки и объяснения
• Голосовые объяснения реакций
• Доступ на 31 день

**Почему элементы:**
• Основа всей химии
• Систематизация знаний
• Практика с реальными задачами
• Фокус на понимании закономерностей

**Идеально для:** тех, кто хочет разобраться в неорганической химии""",

		"full": """**Полный доступ — 3990 ₽**

**Что включено:**
• Всё без ограничений на 31 день
• Все блоки: "Начала химии", "Органика", "Элементы"
• Безлимитные тесты по всем темам
• Неограниченные подсказки и объяснения
• Безлимитные вопросы к ИИ
• Безлимитные голосовые сообщения
• Полные карточки с объяснениями
• Неограниченные отчёты
• Приоритетная поддержка

**Преимущества полного доступа:**
• Максимальная эффективность обучения
• Никаких ограничений
• Возможность попробовать всё
• Лучший результат за короткое время

**Идеально для:** тех, кто хочет максимум и готов инвестировать в результат"""
	}
	
	return descriptions.get(plan_code, "Описание тарифа недоступно")


def tariffs_kb(user_id: int = None) -> InlineKeyboardMarkup:
	rows = []
	
	# Показываем кнопку "Групповые" только если пользователь добавлен в группу преподавателя
	if user_id and is_student_approved_by_teacher(user_id):
		rows.append([InlineKeyboardButton(text="👨‍🏫 Групповые — 390 ₽/мес", callback_data="buy_group")])
	
	# Остальные кнопки всегда показываем
	rows.extend([
	    [InlineKeyboardButton(text="📘 Самоподготовка — 990 ₽/мес", callback_data="buy_self")],
	    [InlineKeyboardButton(text="🧬 Органика — 2990 ₽", callback_data="buy_organic")],
	    [InlineKeyboardButton(text="⚗️ Химия элементов — 2990 ₽", callback_data="buy_elements")],
	    [InlineKeyboardButton(text="🌟 Полный доступ — 3990 ₽", callback_data="buy_full")],
	    [InlineKeyboardButton(text="📞 Бесплатное занятие", callback_data="trial")],
	    [InlineKeyboardButton(text="⬅️ В меню", callback_data="to_main_menu")],
	])
	return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(lambda m: (m.text or "").strip() in {"💳 Тарифы и оплата", "/tariffs"})
async def tariffs(m: types.Message):
	plan = get_user_plan_code(m.from_user.id)
	txt = (
	    "**Выбери тариф:**\n\n"
	    "**Бесплатно**\n"
	    "• Тесты, по 5 подсказок и 3 объяснения/день\n"
	    "• Блок 'Начала химии'\n"
	    "• 2 вопроса ИИ/день\n"
	    "• 1 голосовое сообщение/день\n"
	    "• 1 отчёт/месяц\n"
	    "• Карточки — только заучивание\n"
	    "• 20 решений задач/месяц\n\n"
	    "**Групповые — 390 ₽/мес**\n"
	    "• Полный доступ ко всем функциям\n\n"
	    "**Самоподготовка — 990 ₽/мес**\n"
	    "• Полный доступ ко всем функциям\n\n"
	    "**Органика — 2990 ₽**\n"
	    "• Блок 'Органика', безлимитные тесты\n"
	    "• Практика/ошибки по органике\n\n"
	    "**Химия элементов — 2990 ₽**\n"
	    "• Блок 'Элементы', безлимитные тесты\n"
	    "• Практика/ошибки по неорганике\n\n"
	    "**Полный доступ — 3990 ₽**\n"
	    "• Всё без ограничений\n\n"
	    f"**Текущий план:** {plan}"
	)
	await m.answer(txt, reply_markup=tariffs_kb(m.from_user.id), parse_mode="Markdown")


@router.callback_query(lambda c: c.data.startswith("buy_"))
async def buy_plan(cb: types.CallbackQuery):
	plan_code = cb.data.split("_", 1)[1]
	
	# Сначала показываем подробное описание тарифа
	description = get_tariff_description(plan_code)
	
	kb = InlineKeyboardMarkup(inline_keyboard=[
	    [InlineKeyboardButton(text="💳 Оплатить сейчас", callback_data=f"confirm_buy_{plan_code}")],
	    [InlineKeyboardButton(text="⬅️ Назад к тарифам", callback_data="tariffs_back")],
	])
	
	await cb.message.answer(description, reply_markup=kb, parse_mode="Markdown")
	await cb.answer()


@router.callback_query(lambda c: c.data.startswith("confirm_buy_"))
async def confirm_buy_plan(cb: types.CallbackQuery):
	plan_code = cb.data.split("_", 2)[2]
	
	try:
		pid, url = create_payment(cb.from_user.id, plan_code)
	except Exception as e:
		await cb.message.answer(f"Не удалось создать платёж: {e}")
		await cb.answer()
		return
	
	kb = InlineKeyboardMarkup(inline_keyboard=[
	    [InlineKeyboardButton(text="💳 Оплатить", url=url)],
	    [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"checkpay_{pid}")],
	    [InlineKeyboardButton(text="⬅️ Назад", callback_data="tariffs_back")],
	])
	await cb.message.answer(f"Счёт на тариф «{plan_code}» создан. После оплаты нажми 'Проверить'.", reply_markup=kb)
	await cb.answer()


@router.callback_query(lambda c: c.data.startswith("checkpay_"))
async def on_checkpay(cb: types.CallbackQuery):
	pid = cb.data.split("_", 1)[1]
	try:
		status = check_payment(pid)
	except Exception as e:
		await cb.message.answer(f"Ошибка проверки платежа: {e}")
		await cb.answer()
		return
	
	if status == "succeeded":
		# Узнаем оплаченный тариф из таблицы payments
		code = None
		try:
			with sqlite3.connect(DB_FILE) as conn:
				c = conn.cursor()
				c.execute("SELECT plan_code FROM payments WHERE payment_id=?", (pid,))
				row = c.fetchone()
				code = row[0] if row else None
		except Exception:
			code = None
		if code:
			set_user_plan(cb.from_user.id, code, days=31)
			await cb.message.answer("Оплата подтверждена ✅ Тариф активирован на 31 день.")
		else:
			await cb.message.answer("Оплата подтверждена ✅. Если тариф не активировался — открой '💳 Тарифы и оплата'.")
		await cb.answer("Оплачено ✅")
	else:
		await cb.answer(f"Статус платежа: {status}", show_alert=True)


@router.callback_query(lambda c: c.data == "trial")
async def trial(cb: types.CallbackQuery):
	description = """**Бесплатное занятие**

**Что включено:**
• Персональное занятие с преподавателем
• Диагностику твоих знаний
• План обучения под твои цели
• Ответы на все вопросы
• Пробный доступ к боту

**Почему стоит попробовать:**
• Никаких обязательств
• Понятно, подходит ли тебе формат
• Узнаешь свои слабые места
• Получишь мотивацию к изучению химии

**Идеально для:** тех, кто хочет попробовать, но сомневается"""
	
	kb = InlineKeyboardMarkup(inline_keyboard=[
	    [InlineKeyboardButton(text="📞 Записаться на занятие", callback_data="confirm_trial")],
	    [InlineKeyboardButton(text="⬅️ Назад к тарифам", callback_data="tariffs_back")],
	])
	
	await cb.message.answer(description, reply_markup=kb, parse_mode="Markdown")
	await cb.answer()


@router.callback_query(lambda c: c.data == "confirm_trial")
async def confirm_trial(cb: types.CallbackQuery):
	chat_id = int(os.getenv("TRIAL_CHAT_ID", "0") or 0)
	if chat_id:
		try:
			await cb.message.bot.send_message(
			    chat_id=chat_id,
			    text=f"Заявка на бесплатное занятие: @{cb.from_user.username or '—'} (id {cb.from_user.id}), имя: {cb.from_user.full_name}"
			)
			await cb.message.answer("✅ Заявка отправлена! Мы свяжемся с тобой в ближайшее время.")
		except Exception:
			await cb.message.answer("Не удалось отправить заявку. Напиши, пожалуйста, в личные сообщения преподавателю.")
	else:
		await cb.message.answer("Напиши 'Хочу бесплатное занятие' и оставь телефон — мы свяжемся с тобой.")
	await cb.answer()


@router.callback_query(lambda c: c.data == "tariffs_back")
async def tariffs_back(cb: types.CallbackQuery):
	await cb.message.answer("Тарифы и оплата:", reply_markup=tariffs_kb(cb.from_user.id))
	await cb.answer()


@router.message(lambda m: (m.text or "").strip() == "📞 Бесплатное занятие")
async def trial_message(m: types.Message):
	chat_id = int(os.getenv("TRIAL_CHAT_ID", "0") or 0)
	if chat_id:
		try:
			await m.bot.send_message(
			    chat_id=chat_id,
			    text=f"Заявка на бесплатное занятие: @{m.from_user.username or '—'} (id {m.from_user.id}), имя: {m.from_user.full_name}"
			)
			await m.answer("Заявка отправлена! Мы свяжемся с тобой.")
		except Exception:
			await m.answer("Не удалось отправить заявку. Напишите преподавателю напрямую.")
	else:
		await m.answer("Напиши 'Хочу бесплатное занятие' и оставь телефон — мы свяжемся с тобой.")


@router.callback_query(lambda c: c.data == "to_tariffs")
async def to_tariffs_cb(cb: types.CallbackQuery):
	await cb.message.answer("Тарифы и оплата:", reply_markup=tariffs_kb(cb.from_user.id))
	await cb.answer()


