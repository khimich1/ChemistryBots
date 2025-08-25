from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os, sqlite3

from bot.services.plan import get_user_plan_code, set_user_plan
from bot.services.billing import create_payment, check_payment, PRICES
from bot.services.answer_db import DB_FILE


router = Router()


def tariffs_kb() -> InlineKeyboardMarkup:
	rows = [
	    [InlineKeyboardButton(text="👨‍🏫 Групповые — 1390 ₽/мес", callback_data="buy_group")],
	    [InlineKeyboardButton(text="📘 Самоподготовка — 990 ₽/мес", callback_data="buy_self")],
	    [InlineKeyboardButton(text="🧬 Органика — 2990 ₽", callback_data="buy_organic")],
	    [InlineKeyboardButton(text="⚗️ Химия элементов — 2990 ₽", callback_data="buy_elements")],
	    [InlineKeyboardButton(text="🌟 Полный доступ — 3990 ₽", callback_data="buy_full")],
	    [InlineKeyboardButton(text="📞 Бесплатное занятие", callback_data="trial")],
	    [InlineKeyboardButton(text="⬅️ В меню", callback_data="to_main_menu")],
	]
	return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(lambda m: (m.text or "").strip() in {"💳 Тарифы и оплата", "/tariffs"})
async def tariffs(m: types.Message):
	plan = get_user_plan_code(m.from_user.id)
	txt = (
	    "Выбери тариф:\n\n"
	    "• Бесплатно: тесты, по 5 подсказок и 5 объяснений/день; ‘Начала химии’; 10 вопросов ИИ/день; 20 голосовых/день; 1 отчёт/месяц; карточки — только заучивание.\n"
	    "• Групповые 1390 ₽/мес — полный доступ.\n"
	    "• Самоподготовка 990 ₽/мес — полный доступ.\n"
	    "• Органика 2990 ₽ — блок ‘Органика’, безлимитные тесты, практика/ошибки по органике.\n"
	    "• Химия элементов 2990 ₽ — блок ‘Элементы’, безлимитные тесты, практика/ошибки по неорганике.\n"
	    "• Полный доступ 3990 ₽ — всё без ограничений.\n\n"
	    f"Текущий план: {plan}"
	)
	await m.answer(txt, reply_markup=tariffs_kb())


@router.callback_query(lambda c: c.data.startswith("buy_"))
async def buy_plan(cb: types.CallbackQuery):
	plan_code = cb.data.split("_", 1)[1]
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
	await cb.message.answer(f"Счёт на тариф «{plan_code}» создан. После оплаты нажми ‘Проверить’.", reply_markup=kb)
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
			await cb.message.answer("Оплата подтверждена ✅. Если тариф не активировался — открой ‘💳 Тарифы и оплата’.")
		await cb.answer("Оплачено ✅")
	else:
		await cb.answer(f"Статус платежа: {status}", show_alert=True)


@router.callback_query(lambda c: c.data == "trial")
async def trial(cb: types.CallbackQuery):
	chat_id = int(os.getenv("TRIAL_CHAT_ID", "0") or 0)
	if chat_id:
		try:
			await cb.message.bot.send_message(
			    chat_id=chat_id,
			    text=f"Заявка на бесплатное занятие: @{cb.from_user.username or '—'} (id {cb.from_user.id}), имя: {cb.from_user.full_name}"
			)
			await cb.message.answer("Заявка отправлена! Мы свяжемся с тобой.")
		except Exception:
			await cb.message.answer("Не удалось отправить заявку. Напиши, пожалуйста, в личные сообщения преподавателю.")
	else:
		await cb.message.answer("Напиши ‘Хочу бесплатное занятие’ и оставь телефон — мы свяжемся с тобой.")
	await cb.answer()


@router.callback_query(lambda c: c.data == "tariffs_back")
async def tariffs_back(cb: types.CallbackQuery):
	await cb.message.answer("Тарифы и оплата:", reply_markup=tariffs_kb())
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
		await m.answer("Напиши ‘Хочу бесплатное занятие’ и оставь телефон — мы свяжемся с тобой.")


@router.callback_query(lambda c: c.data == "to_tariffs")
async def to_tariffs_cb(cb: types.CallbackQuery):
	await cb.message.answer("Тарифы и оплата:", reply_markup=tariffs_kb())
	await cb.answer()


