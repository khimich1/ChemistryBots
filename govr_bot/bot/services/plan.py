import sqlite3
from datetime import datetime, timedelta, date
from typing import Optional, Tuple

from bot.services.answer_db import DB_FILE


FREE = "free"
GROUP = "group"
SELF = "self"
ORGANIC = "organic"
ELEMENTS = "elements"
FULL = "full"


def init_billing_tables():

	with sqlite3.connect(DB_FILE) as conn:
		c = conn.cursor()
		c.execute(
			"""CREATE TABLE IF NOT EXISTS user_plans(
			  user_id INTEGER PRIMARY KEY,
			  plan_code TEXT,
			  started_at TEXT,
			  expires_at TEXT,
			  meta TEXT)"""
		)
		c.execute(
			"""CREATE TABLE IF NOT EXISTS plan_usage(
			  user_id INTEGER,
			  period TEXT,
			  key TEXT,
			  count INTEGER DEFAULT 0,
			  PRIMARY KEY(user_id, period, key))"""
		)
		c.execute(
			"""CREATE TABLE IF NOT EXISTS payments(
			  payment_id TEXT PRIMARY KEY,
			  user_id INTEGER,
			  plan_code TEXT,
			  amount INTEGER,
			  currency TEXT,
			  status TEXT,
			  created_at TEXT,
			  paid_at TEXT)"""
		)
		conn.commit()


def get_user_plan_code(user_id: int) -> str:
	with sqlite3.connect(DB_FILE) as conn:
		c = conn.cursor()
		c.execute("SELECT plan_code, expires_at FROM user_plans WHERE user_id=?", (user_id,))
		row = c.fetchone()
		if not row:
			return FREE
		plan, expires = row[0], row[1]
		if expires and (expires or "").strip():
			try:
				if datetime.now() > datetime.strptime(expires, "%Y-%m-%d %H:%M:%S"):
					return FREE
			except Exception:
				pass
		return plan or FREE


def set_user_plan(user_id: int, plan_code: str, days: int = 31) -> None:
	started = datetime.now()
	expires = started + timedelta(days=days)
	with sqlite3.connect(DB_FILE) as conn:
		c = conn.cursor()
		c.execute(
			"""INSERT INTO user_plans(user_id, plan_code, started_at, expires_at, meta)
			             VALUES(?,?,?,?,?)
			             ON CONFLICT(user_id) DO UPDATE SET plan_code=excluded.plan_code, started_at=excluded.started_at, expires_at=excluded.expires_at""",
			(user_id, plan_code, started.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S"), ""),
		)
		conn.commit()


def _period_day(d: date | None = None) -> str:
	d = d or date.today()
	return d.strftime("%Y-%m-%d")


def _period_month(d: date | None = None) -> str:
	d = d or date.today()
	return d.strftime("%Y-%m")


def get_usage(user_id: int, key: str, period: str) -> int:
	with sqlite3.connect(DB_FILE) as conn:
		c = conn.cursor()
		c.execute("SELECT count FROM plan_usage WHERE user_id=? AND period=? AND key=?", (user_id, period, key))
		row = c.fetchone()
		return int(row[0]) if row and row[0] is not None else 0


def inc_usage(user_id: int, key: str, period: str) -> int:
	with sqlite3.connect(DB_FILE) as conn:
		c = conn.cursor()
		c.execute(
			"""INSERT INTO plan_usage(user_id, period, key, count)
			            VALUES (?,?,?,1)
			            ON CONFLICT(user_id,period,key) DO UPDATE SET count=plan_usage.count+1""",
			(user_id, period, key),
		)
		conn.commit()
		c.execute("SELECT count FROM plan_usage WHERE user_id=? AND period=? AND key=?", (user_id, period, key))
		row = c.fetchone()
		return int(row[0]) if row and row[0] is not None else 0


def limits_for(plan: str) -> dict:
	if plan in (FULL, SELF, GROUP):
		return {
		    "test_hint_per_day": None,
		    "test_explain_per_day": None,
		    "theory_ai_per_day": None,
		    "theory_voice_per_day": None,
		    "reports_per_month": None,
		    "flashcards_modes": {"learn": True, "practice_inorg": True, "practice_org": True, "errors_inorg": True, "errors_org": True},
		    "theory_allowed": {"begin": True, "elements": True, "organic": True},
		}
	if plan == ORGANIC:
		return {
		    "test_hint_per_day": None,
		    "test_explain_per_day": None,
		    "theory_ai_per_day": None,
		    "theory_voice_per_day": None,
		    "reports_per_month": None,
		    "flashcards_modes": {"learn": True, "practice_inorg": False, "practice_org": True, "errors_inorg": False, "errors_org": True},
		    "theory_allowed": {"begin": True, "elements": False, "organic": True},
		}
	if plan == ELEMENTS:
		return {
		    "test_hint_per_day": None,
		    "test_explain_per_day": None,
		    "theory_ai_per_day": None,
		    "theory_voice_per_day": None,
		    "reports_per_month": None,
		    "flashcards_modes": {"learn": True, "practice_inorg": True, "practice_org": False, "errors_inorg": True, "errors_org": False},
		    "theory_allowed": {"begin": True, "elements": True, "organic": False},
		}
	return {
	    "test_hint_per_day": 5,
	    "test_explain_per_day": 5,
	    "theory_ai_per_day": 10,
	    "theory_voice_per_day": 20,
	    "reports_per_month": 1,
	    "flashcards_modes": {"learn": True, "practice_inorg": False, "practice_org": False, "errors_inorg": False, "errors_org": False},
	    "theory_allowed": {"begin": True, "elements": False, "organic": False},
	}


def can_use_daily(user_id: int, key: str, limit: Optional[int]) -> Tuple[bool, int]:
	if limit is None:
		return True, -1
	used = get_usage(user_id, key, _period_day())
	left = max(0, limit - used)
	return (left > 0), left


def consume_daily(user_id: int, key: str, limit: Optional[int]) -> Tuple[bool, int]:
	if limit is None:
		return True, -1
	used = get_usage(user_id, key, _period_day())
	if used >= limit:
		return False, 0
	used2 = inc_usage(user_id, key, _period_day())
	left = max(0, limit - used2)
	return True, left


def can_use_monthly(user_id: int, key: str, limit: Optional[int]) -> Tuple[bool, int]:
	if limit is None:
		return True, -1
	used = get_usage(user_id, key, _period_month())
	left = max(0, limit - used)
	return (left > 0), left


def consume_monthly(user_id: int, key: str, limit: Optional[int]) -> Tuple[bool, int]:
	if limit is None:
		return True, -1
	used = get_usage(user_id, key, _period_month())
	if used >= limit:
		return False, 0
	used2 = inc_usage(user_id, key, _period_month())
	left = max(0, limit - used2)
	return True, left


def theory_allowed(user_id: int, section: str) -> bool:
	plan = get_user_plan_code(user_id)
	return bool(limits_for(plan)["theory_allowed"].get(section, False))


def flashcards_mode_allowed(user_id: int, mode: str, category: str) -> bool:
	plan = get_user_plan_code(user_id)
	m = limits_for(plan)["flashcards_modes"]
	if mode == "learn":
		return True
	if mode == "practice":
		return m["practice_org"] if category == "org" else m["practice_inorg"]
	if mode == "errors":
		return m["errors_org"] if category == "org" else m["errors_inorg"]
	return False


