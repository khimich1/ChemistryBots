import asyncio
import datetime as dt
import os
import sqlite3
from typing import Optional, Tuple


# Путь к shared/users.db и shared/calendar.db относительно корня репозитория
def _repo_root() -> str:
    # services -> bot -> govr_bot -> <repo_root>
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _shared_path(name: str) -> str:
    return os.path.join(_repo_root(), "shared", name)


USERS_DB = _shared_path("users.db")
CAL_DB = _shared_path("calendar.db")


def _ensure_sent_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_reminders (
            key TEXT PRIMARY KEY,
            sent_at TEXT
        )
        """
    )
    conn.commit()


def _upcoming_within(minutes_horizon: int = 60) -> list[dict]:
    """Собирает ближайшие занятия из users.db и calendar.db.
    Возвращает элементы {id, tg_id, day, start, end, kind, target, notify_before_min}.
    """
    now = dt.datetime.now()
    horizon = now + dt.timedelta(minutes=minutes_horizon)

    def _parse_day_time(day: str, hhmm: str) -> Optional[dt.datetime]:
        try:
            h, m = map(int, (hhmm or "00:00").split(":", 1))
            d = dt.datetime.strptime(day, "%Y-%m-%d")
            return dt.datetime(d.year, d.month, d.day, h, m)
        except Exception:
            return None

    out: list[dict] = []
    # 1) users.db
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, tg_id, day, start, end, kind, target, COALESCE(notify_before_min,30)
                FROM teacher_lessons
                WHERE day >= date('now','localtime')
                """
            )
            for rid, tg_id, day, start, end, kind, target, nb in cur.fetchall():
                sdt = _parse_day_time(str(day), str(start))
                if not sdt:
                    continue
                if now - dt.timedelta(hours=2) <= sdt <= horizon:
                    out.append({
                        "id": int(rid),
                        "tg_id": int(tg_id),
                        "day": str(day),
                        "start": str(start),
                        "end": str(end),
                        "kind": str(kind),
                        "target": str(target),
                        "notify_before_min": int(nb or 30),
                    })
    except Exception:
        pass

    # 2) calendar.db (все cal_* таблицы)
    try:
        with sqlite3.connect(CAL_DB) as conn2:
            cur2 = conn2.cursor()
            cur2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cal_%'")
            tables = [row[0] for row in cur2.fetchall()]
            for tbl in tables:
                try:
                    cur2.execute(
                        f"SELECT id, day, start, end, kind, target, COALESCE(notify_before_min,30) FROM {tbl} WHERE day >= date('now','localtime')"
                    )
                    for rid, day, start, end, kind, target, nb in cur2.fetchall():
                        sdt = _parse_day_time(str(day), str(start))
                        if not sdt:
                            continue
                        if now - dt.timedelta(hours=2) <= sdt <= horizon:
                            out.append({
                                "id": int(rid),
                                "tg_id": None,
                                "day": str(day),
                                "start": str(start),
                                "end": str(end),
                                "kind": str(kind),
                                "target": str(target),
                                "notify_before_min": int(nb or 30),
                            })
                except Exception:
                    continue
    except Exception:
        pass

    return out


def _make_key(item: dict, kind: str) -> str:
    # key гарантирует уникальность: источник+lesson_id+kind+day+start
    return f"{kind}:{item.get('id')}:{item.get('day')}:{item.get('start')}"


async def _send_to_group(bot, group_no: int, text: str) -> Tuple[int, int]:
    from ...services.answer_db import get_conn
    # На стороне govr бота нет прямой таблицы групп; рассылка по списку work_groups делается через prepod, поэтому
    # используем простой broadcast: у нас его нет здесь. Отправим напрямую по user_plans 'group' не корректно.
    # Выберем путь: попытаемся прочитать файл prepod_bot DB work_groups, если есть.
    ok = 0
    fail = 0
    try:
        from aiogram import Bot
        # Используем текущий bot
        # Таблица work_groups хранится в общей базе prepod_bot (shared/test_answers.db)
        db_path = os.path.join(_repo_root(), "shared", "test_answers.db")
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS work_groups (
                    group_no INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    added_at TEXT,
                    PRIMARY KEY (group_no, user_id)
                )
                """
            )
            cur.execute("SELECT user_id FROM work_groups WHERE group_no=?", (int(group_no),))
            ids = [int(r[0]) for r in cur.fetchall()]
        for uid in ids:
            try:
                await bot.send_message(uid, text)
                ok += 1
            except Exception:
                fail += 1
    except Exception:
        pass
    return ok, fail


async def reminders_loop(bot, *, check_interval_s: float = 30.0):
    """Фоновая задача: раз в N секунд ищет занятия, для которых пора слать напоминание, и шлёт.
    Дедупликация через таблицу sent_reminders в users.db (общей базе govr/prepod).
    """
    while True:
        try:
            now = dt.datetime.now()
            items = _upcoming_within(90)
            if items:
                with sqlite3.connect(USERS_DB) as conn:
                    _ensure_sent_table(conn)
                    cur = conn.cursor()
                    for it in items:
                        # Когда напоминать
                        start_dt = dt.datetime.strptime(f"{it['day']} {it['start']}", "%Y-%m-%d %H:%M")
                        notify_at = start_dt - dt.timedelta(minutes=int(it.get("notify_before_min") or 30))
                        # Отправляем только если окно наступило в последние 2 мин и не отправляли ранее
                        if not (notify_at <= now <= notify_at + dt.timedelta(minutes=2)):
                            continue
                        key = _make_key(it, "notify")
                        cur.execute("SELECT 1 FROM sent_reminders WHERE key=?", (key,))
                        if cur.fetchone():
                            continue
                        # Формируем текст
                        time_label = start_dt.strftime("%H:%M")
                        if it.get("kind") == "group":
                            try:
                                group_no = int((it.get("target") or "").lstrip("# ").strip())
                            except Exception:
                                group_no = 0
                            if group_no:
                                text = f"Напоминание: через {int(it.get('notify_before_min') or 30)} мин занятие группы {group_no} в {time_label}."
                                try:
                                    ok, _ = await _send_to_group(bot, group_no, text)
                                except Exception:
                                    ok = 0
                                if ok:
                                    cur.execute("INSERT OR REPLACE INTO sent_reminders(key, sent_at) VALUES(?, datetime('now','localtime'))", (key,))
                                    conn.commit()
                        else:
                            # personal
                            from ...services.answer_db import get_conn
                            # Попробуем извлечь user_id из target: @username/ID NNN
                            uid: Optional[int] = None
                            t = (it.get("target") or "").strip()
                            # ID
                            import re
                            m = re.search(r"\bID\s*(\d+)\b", t, flags=re.IGNORECASE)
                            if m:
                                try:
                                    uid = int(m.group(1))
                                except Exception:
                                    uid = None
                            if uid is None and "@" in t:
                                uname = None
                                for part in t.replace("\n", " ").split(" "):
                                    if part.startswith("@"):
                                        uname = part[1:]
                                if uname:
                                    # Ищем в общей answers DB по username
                                    try:
                                        with sqlite3.connect(os.path.join(_repo_root(), "shared", "test_answers.db")) as aconn:
                                            acur = aconn.cursor()
                                            acur.execute("SELECT user_id FROM test_answers WHERE LOWER(NULLIF(TRIM(username),'')) = ? ORDER BY id DESC LIMIT 1", (uname.lower(),))
                                            row = acur.fetchone()
                                            if row:
                                                uid = int(row[0])
                                    except Exception:
                                        uid = None
                            # Fallback: пробуем точное совпадение по full_name, если username/ID не сработали
                            if uid is None and t:
                                try:
                                    with sqlite3.connect(os.path.join(_repo_root(), "shared", "test_answers.db")) as aconn:
                                        acur = aconn.cursor()
                                        acur.execute(
                                            """
                                            SELECT user_id FROM test_answers
                                            WHERE LOWER(NULLIF(TRIM(full_name),'')) = ?
                                            ORDER BY id DESC LIMIT 1
                                            """,
                                            (t.lower(),)
                                        )
                                        row = acur.fetchone()
                                        if row:
                                            uid = int(row[0])
                                except Exception:
                                    pass
                            if uid:
                                text = f"Напоминание: через {int(it.get('notify_before_min') or 30)} мин занятие в {time_label}."
                                try:
                                    await bot.send_message(int(uid), text)
                                    cur.execute("INSERT OR REPLACE INTO sent_reminders(key, sent_at) VALUES(?, datetime('now','localtime'))", (key,))
                                    conn.commit()
                                except Exception:
                                    pass
        except Exception:
            # защищаемся от любых падений в фоне
            pass
        await asyncio.sleep(check_interval_s)



