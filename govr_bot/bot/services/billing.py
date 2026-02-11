import os
import sqlite3
from datetime import datetime
import uuid

from bot.services.answer_db import DB_FILE, get_conn


# Параметры YooKassa из окружения
YK_SHOP_ID = os.getenv("YK_SHOP_ID", "").strip()
YK_SECRET_KEY = os.getenv("YK_SECRET_KEY", "").strip()
RETURN_URL = os.getenv("YK_RETURN_URL", "https://t.me/").strip()


# Цены в рублях
PRICES: dict[str, int] = {
	"group": 0,
	"self": 390,
	"organic": 2990,
	"elements": 2990,
	"full": 3990,
}


def _ensure_payments_table():
	"""Создаёт таблицу payments если она не существует."""
	with get_conn() as conn:
		c = conn.cursor()
		c.execute("""
			CREATE TABLE IF NOT EXISTS payments(
				payment_id TEXT PRIMARY KEY,
				user_id INTEGER,
				plan_code TEXT,
				amount INTEGER,
				currency TEXT,
				status TEXT,
				created_at TEXT,
				paid_at TEXT
			)
		""")
		conn.commit()


def _ensure_yookassa_configured():
	"""Ленивая инициализация SDK YooKassa внутри функций, чтобы импорт не падал при старте.

	Поднимем понятную ошибку, если пакет не установлен или ключи не заданы.
	"""
	if not YK_SHOP_ID or not YK_SECRET_KEY:
		raise RuntimeError("Не заданы YK_SHOP_ID/YK_SECRET_KEY в .env для YooKassa")
	try:
		from yookassa import Configuration  # type: ignore
		Configuration.account_id = YK_SHOP_ID
		Configuration.secret_key = YK_SECRET_KEY
	except ModuleNotFoundError as e:
		raise RuntimeError("Не установлен пакет yookassa. Установи: pip install yookassa") from e


def create_payment(user_id: int, plan_code: str, *, customer_phone: str | None = None, customer_email: str | None = None) -> tuple[str, str]:
	"""Создаёт платёж и возвращает (payment_id, confirmation_url).

	Для самозанятого требуется чек (receipt). Нужен телефон или email покупателя.
	"""
	_ensure_yookassa_configured()
	from yookassa import Payment  # type: ignore

	amount = PRICES[plan_code]
	description = f"ChemistryBot: тариф {plan_code} для user {user_id}"
	if not customer_phone and not customer_email:
		raise ValueError("Нужен телефон или email покупателя для чека")

	receipt = {
		"customer": ({"phone": customer_phone} if customer_phone else {"email": customer_email}),
		"items": [{
			"description": f"ChemistryBot: тариф {plan_code}",
			"quantity": "1.00",
			"amount": {"value": f"{float(amount):.2f}", "currency": "RUB"},
			"payment_subject": "service",
			"payment_mode": "full_prepayment",
			"vat_code": 1,
		}],
	}

	idempotence_key = str(uuid.uuid4())
	payment = Payment.create({
	    "amount": {"value": f"{float(amount):.2f}", "currency": "RUB"},
	    "receipt": receipt,
	    "confirmation": {"type": "redirect", "return_url": RETURN_URL},
	    "capture": True,
	    "description": description,
	    "metadata": {"user_id": user_id, "plan_code": plan_code},
	}, idempotence_key)
	pid = payment.id
	url = payment.confirmation.confirmation_url
	
	# Создаём таблицу если её нет
	_ensure_payments_table()
	
	with get_conn() as conn:
		c = conn.cursor()
		c.execute(
			"""INSERT OR REPLACE INTO payments(payment_id, user_id, plan_code, amount, currency, status, created_at)
			             VALUES (?,?,?,?,?,?,?)""",
			(pid, user_id, plan_code, amount, "RUB", str(payment.status), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
		)
		conn.commit()
	return pid, url


def check_payment(payment_id: str) -> str:
	"""Возвращает статус платежа и обновляет его в БД."""
	_ensure_yookassa_configured()
	from yookassa import Payment  # type: ignore

	p = Payment.find_one(payment_id)
	status = str(p.status)
	
	# Создаём таблицу если её нет
	_ensure_payments_table()
	
	with get_conn() as conn:
		c = conn.cursor()
		c.execute(
			"UPDATE payments SET status=?, paid_at=? WHERE payment_id=?",
			(status, datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "succeeded" else None, payment_id),
		)
		conn.commit()
	return status


