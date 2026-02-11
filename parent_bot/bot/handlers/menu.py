from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, FSInputFile

from bot.services.db import get_user, upsert_user, init_users_db
from bot.services.gpt_service import chat_with_gpt
from aiogram.fsm.state import State, StatesGroup

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# Пути к общим БД (корень всего репозитория ChemistryBots)
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
TEST_ANSWERS_DB = os.path.join(SHARED_DIR, "test_answers.db")

# Директория govr_bot (для запуска генератора отчёта)
GOVR_BOT_DIR = os.path.join(REPO_ROOT, "govr_bot")

# Импортируем модуль из services
from bot.services.filename_generator import get_filename_for_user

router = Router()


class Onboarding(StatesGroup):
	waiting_parent_name = State()
	waiting_child_nick = State()
	waiting_child_nick_for_report = State()


main_kb = ReplyKeyboardMarkup(
	keyboard=[
		[KeyboardButton(text="📊 Отчёт об успеваемости")],
		[KeyboardButton(text="💳 Оплата занятий")],
		[KeyboardButton(text="🤖 Доступ к GPT")],
	],
	resize_keyboard=True,
)


@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
	init_users_db()
	user = get_user(message.from_user.id)
	# Если записи нет — создадим пустую (с username) и начнём онбординг
	if not user:
		upsert_user(message.from_user.id, parent_username=message.from_user.username)
		await state.set_state(Onboarding.waiting_parent_name)
		await message.answer("Здравствуйте! Как вас зовут? Напишите имя и фамилию.")
		return

	parent_name, child_nick, parent_username = user
	parent_name = (parent_name or "").strip()
	child_nick = (child_nick or "").strip()
	if not parent_username:
		upsert_user(message.from_user.id, parent_username=message.from_user.username)

	# Если уже всё заполнено — сразу показываем меню без вопросов
	if parent_name and child_nick:
		await state.clear()
		await message.answer("С возвращением! Выберите действие:", reply_markup=main_kb)
		return

	# Иначе дособираем недостающие поля
	if not parent_name:
		await state.set_state(Onboarding.waiting_parent_name)
		await message.answer("Здравствуйте! Как вас зовут? Напишите имя и фамилию.")
		return
	if not child_nick:
		await state.set_state(Onboarding.waiting_child_nick)
		await message.answer("Отлично! Теперь пришлите ник в Telegram вашего ребёнка (например, @nickname)")
		return


@router.message(Onboarding.waiting_parent_name)
async def parent_name_received(message: Message, state: FSMContext):
	upsert_user(message.from_user.id, parent_name=message.text.strip())
	await state.set_state(Onboarding.waiting_child_nick)
	await message.answer("Отлично! Теперь пришлите ник в Telegram вашего ребёнка (например, @nickname)")


@router.message(Onboarding.waiting_child_nick)
async def child_nick_received(message: Message, state: FSMContext):
	upsert_user(message.from_user.id, child_nick=message.text.strip())
	await state.clear()
	await message.answer("Спасибо! Данные сохранены.", reply_markup=main_kb)


def _find_student_user_id_by_nick(nick: str) -> int | None:
	nick = (nick or "").lstrip("@").strip()
	if not nick:
		return None
	with sqlite3.connect(TEST_ANSWERS_DB) as conn:
		c = conn.cursor()
		c.execute(
			"""
			SELECT user_id
			FROM test_answers
			WHERE REPLACE(LOWER(username),'@','') = LOWER(?)
			ORDER BY answer_time DESC
			LIMIT 1
			""",
			(nick,),
		)
		row = c.fetchone()
		return int(row[0]) if row else None


def _generate_report_pdf(user_id: int, fallback_name: str | None = None) -> str:
	"""Вызывает генератор отчёта из govr_bot и возвращает путь к PDF."""
	# Используем интерпретатор из venv govr_bot, чтобы были все зависимости (matplotlib, reportlab)
	govr_python = os.path.join(GOVR_BOT_DIR, "venv", "bin", "python")
	python_exe = govr_python if os.path.exists(govr_python) else os.getenv("PYTHON", "python3")
	
	# Генерируем имя файла с использованием общего модуля
	filename = get_filename_for_user(user_id, fallback_name, None)
	out_path = str(Path(os.path.join(SHARED_DIR, filename)).resolve())
	
	# Запускаем CLI из каталога govr_bot, чтобы работали относительные импорты
	cmd = [python_exe, "-m", "bot.services.report_cli", "--user-id", str(user_id), "--output", out_path]
	if fallback_name:
		cmd += ["--fallback-name", fallback_name]
	res = subprocess.run(cmd, cwd=GOVR_BOT_DIR, capture_output=True, text=True)
	# stdout печатает финальный путь; если не удалось — всё равно вернём ожидаемый out_path
	return (res.stdout.strip() or out_path)


def _safe_unlink(path: str) -> None:
	try:
		if path and os.path.exists(path):
			os.remove(path)
	except Exception:
		pass


@router.message(F.text.in_({"📊 Отчёт об успеваемости", "💳 Оплата занятий"}))
async def stubs(message: Message, state: FSMContext):
	if message.text == "📊 Отчёт об успеваемости":
		init_users_db()
		user = get_user(message.from_user.id)
		child_nick = user[1] if user else None
		if not child_nick or not child_nick.strip():
			await state.set_state(Onboarding.waiting_child_nick_for_report)
			await message.answer("У меня нет ника ученика. Пришлите ник (например, @nickname)")
			return
		student_id = _find_student_user_id_by_nick(child_nick)
		if not student_id:
			await message.answer("Не нашёл такого ученика в базе ответов. Убедитесь, что он проходил тесты.")
			return
		pdf_path = _generate_report_pdf(student_id, fallback_name=child_nick)
		try:
			await message.answer_document(FSInputFile(pdf_path), caption=f"Отчёт для {child_nick}")
		finally:
			_safe_unlink(pdf_path)
	else:
		await message.answer("Оплата занятий: скоро будет доступна.")


@router.message(Onboarding.waiting_child_nick_for_report)
async def child_nick_for_report(message: Message, state: FSMContext):
	child_nick = (message.text or "").strip()
	upsert_user(message.from_user.id, child_nick=child_nick)
	await state.clear()
	student_id = _find_student_user_id_by_nick(child_nick)
	if not student_id:
		await message.answer("Не нашёл такого ученика в базе ответов. Убедитесь, что он проходил тесты.")
		return
	pdf_path = _generate_report_pdf(student_id, fallback_name=child_nick)
	try:
		await message.answer_document(FSInputFile(pdf_path), caption=f"Отчёт для {child_nick}")
	finally:
		_safe_unlink(pdf_path)


@router.message(F.text == "🤖 Доступ к GPT")
async def gpt_entry(message: Message):
	user = get_user(message.from_user.id)
	parent_name = (user[0] if user else None) or "родитель"
	await message.answer(
		"Напишите сообщение для GPT. История последних 20 сообщений сохраняется.\n"
		"Чтобы очистить память, отправьте: /reset"
	)


@router.message(F.text & ~F.text.in_({"📊 Отчёт об успеваемости", "💳 Оплата занятий", "🤖 Доступ к GPT"}))
async def gpt_chat(message: Message):
	user = get_user(message.from_user.id)
	parent_name = (user[0] if user else None) or "родитель"
	system = f"Ты дружелюбный ассистент для родителя по имени {parent_name}. Отвечай кратко и по делу."
	try:
		answer = await chat_with_gpt(message.from_user.id, system, message.text)
	except Exception as e:
		await message.answer(f"GPT недоступен: {e}")
		return
	await message.answer(answer)


