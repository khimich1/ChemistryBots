import sqlite3
from typing import List, Dict, Tuple, Optional
import datetime as dt

from config import USERS_DB, CALENDAR_DB


def _ensure_table() -> None:
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS teacher_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id INTEGER NOT NULL,
                    day TEXT NOT NULL,      -- YYYY-MM-DD
                    start TEXT NOT NULL,    -- HH:MM
                    end TEXT NOT NULL,      -- HH:MM
                    kind TEXT NOT NULL,     -- student|group
                    target TEXT NOT NULL,   -- @username или номер группы
                    notify_before_min INTEGER DEFAULT 30
                )
                """
            )
            conn.commit()
            # Backfill: add notify_before_min if the table existed before
            try:
                cur.execute("PRAGMA table_info(teacher_lessons)")
                cols = {row[1] for row in cur.fetchall()}
                if "notify_before_min" not in cols:
                    cur.execute("ALTER TABLE teacher_lessons ADD COLUMN notify_before_min INTEGER DEFAULT 30")
                    conn.commit()
            except Exception:
                pass
    except Exception:
        pass


def _ensure_calendar_table(moniker: str) -> None:
    """Гарантирует наличие таблицы календаря для преподавателя в CALENDAR_DB.
    Имя таблицы — латинизированный монникер, небуквенно-цифровые символы заменяются на '_'.
    Структура: id, day, start, end, kind, target, note
    """
    safe_name = _safe_table_name(moniker)
    try:
        with sqlite3.connect(CALENDAR_DB) as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {safe_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    start TEXT NOT NULL,
                    end TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    note TEXT,
                    notify_before_min INTEGER DEFAULT 30
                )
                """
            )
            conn.commit()
            # Миграция добавочного столбца
            try:
                cur.execute(f"PRAGMA table_info({safe_name})")
                cols = {row[1] for row in cur.fetchall()}
                if "notify_before_min" not in cols:
                    cur.execute(f"ALTER TABLE {safe_name} ADD COLUMN notify_before_min INTEGER DEFAULT 30")
                    conn.commit()
            except Exception:
                pass
    except Exception:
        pass


def _safe_table_name(name: str) -> str:
    import re
    name = (name or "teacher").lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_") or "teacher"
    return f"cal_{name}"


def add_lesson(tg_id: int, *, day: str, start: str, end: str, kind: str, target: str) -> None:
    _ensure_table()
    # Сохраняем в users.db (историческая база)
    with sqlite3.connect(USERS_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO teacher_lessons (tg_id, day, start, end, kind, target, notify_before_min) VALUES (?, ?, ?, ?, ?, ?, 30)",
            (tg_id, day, start, end, kind, target)
        )
        conn.commit()

    # Дублируем в локальный календарь per-teacher таблицу
    try:
        from .teachers import get_teacher_moniker  # локальный импорт, чтобы избежать циклов
        moniker = get_teacher_moniker(tg_id) or f"teacher_{tg_id}"
        _ensure_calendar_table(moniker)
        table = _safe_table_name(moniker)
        with sqlite3.connect(CALENDAR_DB) as conn2:
            cur2 = conn2.cursor()
            cur2.execute(
                f"INSERT INTO {table} (day, start, end, kind, target, note, notify_before_min) VALUES (?, ?, ?, ?, ?, ?, 30)",
                (day, start, end, kind, target, None)
            )
            conn2.commit()
    except Exception:
        pass


def list_lessons_by_day(tg_id: int, *, day: str) -> List[Dict]:
    """Возвращает список уроков преподавателя на указанный день.
    Элемент: {id, day, start, end, kind, target}
    """
    _ensure_table()
    with sqlite3.connect(USERS_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, day, start, end, kind, target, COALESCE(notify_before_min,30) FROM teacher_lessons WHERE tg_id=? AND day=? ORDER BY start",
            (tg_id, day),
        )
        rows = cur.fetchall()
    out: List[Dict] = []
    for r in rows:
        out.append({
            "id": int(r[0]),
            "day": str(r[1]),
            "start": str(r[2]),
            "end": str(r[3]),
            "kind": str(r[4]),
            "target": str(r[5]),
            "notify_before_min": int(r[6] or 30),
        })
    # Дополнительно подмешаем записи из локального календаря (если они ещё не в users.db)
    try:
        from .teachers import get_teacher_moniker
        moniker = get_teacher_moniker(tg_id) or f"teacher_{tg_id}"
        _ensure_calendar_table(moniker)
        table = _safe_table_name(moniker)
        with sqlite3.connect(CALENDAR_DB) as conn2:
            cur2 = conn2.cursor()
            cur2.execute(f"SELECT id, day, start, end, kind, target, COALESCE(notify_before_min,30) FROM {table} WHERE day=? ORDER BY start", (day,))
            for cid, d, s, e, k, t, nb in cur2.fetchall():
                # Найдём дубль по (start,end,kind,target)
                if not any(x["start"] == s and x["end"] == e and x["kind"] == k and x["target"] == t for x in out):
                    out.append({
                        "id": cid,  # id другой базы — для действий будем различать через negative/positive? оставим как есть
                        "day": d,
                        "start": s,
                        "end": e,
                        "kind": k,
                        "target": t,
                        "notify_before_min": int(nb or 30),
                    })
    except Exception:
        pass
    return out


def update_lesson_time(lesson_id: int, *, start: str, end: str) -> bool:
    """Меняет время урока. Возвращает True, если запись обновлена."""
    _ensure_table()
    with sqlite3.connect(USERS_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE teacher_lessons SET start=?, end=? WHERE id=?",
            (start, end, lesson_id),
        )
        conn.commit()
        ok1 = cur.rowcount > 0
    # Попробуем обновить и в локальном календаре (во всех таблицах — простая реализация)
    ok2 = False
    try:
        with sqlite3.connect(CALENDAR_DB) as conn2:
            cur2 = conn2.cursor()
            # Перебор всех таблиц cal_*
            cur2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cal_%'")
            for (tbl,) in cur2.fetchall():
                cur2.execute(f"UPDATE {tbl} SET start=?, end=? WHERE id=?", (start, end, lesson_id))
                if cur2.rowcount:
                    ok2 = True
            conn2.commit()
    except Exception:
        pass
    return ok1 or ok2


def delete_lesson(lesson_id: int) -> bool:
    """Удаляет урок по id. Возвращает True при успехе."""
    _ensure_table()
    with sqlite3.connect(USERS_DB) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM teacher_lessons WHERE id=?", (lesson_id,))
        conn.commit()
        ok1 = cur.rowcount > 0
    ok2 = False
    try:
        with sqlite3.connect(CALENDAR_DB) as conn2:
            cur2 = conn2.cursor()
            cur2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cal_%'")
            for (tbl,) in cur2.fetchall():
                cur2.execute(f"DELETE FROM {tbl} WHERE id=?", (lesson_id,))
                if cur2.rowcount:
                    ok2 = True
            conn2.commit()
    except Exception:
        pass
    return ok1 or ok2


def find_free_slot(day: str, *, duration_min: int = 60, bounds: Tuple[str, str] = ("09:00", "21:00"), busy: Optional[List[Tuple[str, str]]] = None) -> Tuple[str, str] | None:
    """Простейший поиск свободного окна в пределах bounds.
    bounds: (start, end) строки HH:MM. busy — список занятых интервалов HH:MM-HH:MM.
    Возвращает (start, end) или None.
    """
    def to_minutes(hhmm: str) -> int:
        h, m = (hhmm or "00:00").split(":", 1)
        return int(h) * 60 + int(m)

    b_start, b_end = to_minutes(bounds[0]), to_minutes(bounds[1])
    intervals: List[Tuple[int, int]] = []
    for s, e in (busy or []):
        intervals.append((to_minutes(s), to_minutes(e)))
    intervals.sort()

    cur = b_start
    for s, e in intervals:
        if cur + duration_min <= s:
            return (f"{cur//60:02d}:{cur%60:02d}", f"{(cur+duration_min)//60:02d}:{(cur+duration_min)%60:02d}")
        cur = max(cur, e)
    if cur + duration_min <= b_end:
        return (f"{cur//60:02d}:{cur%60:02d}", f"{(cur+duration_min)//60:02d}:{(cur+duration_min)%60:02d}")
    return None


def get_lessons_in_week(tg_id: int, week_start: dt.datetime, week_end: dt.datetime) -> Dict[str, List[Dict]]:
    """Возвращает словарь label -> список событий-уроков за неделю.
    label = 'Mon, 23.09'
    """
    _ensure_table()
    start_day = week_start.date()
    end_day = week_end.date()
    days: List[str] = []
    cur = start_day
    while cur <= end_day:
        days.append(cur.strftime("%Y-%m-%d"))
        cur = cur + dt.timedelta(days=1)

    by_label: Dict[str, List[Dict]] = {}
    ru_full = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    def _label_for(day_dt: dt.datetime) -> str:
        return f"{ru_full[day_dt.weekday()]}, {day_dt.strftime('%d.%m')}"
    # Набор уже добавленных событий, чтобы избежать дублей между источниками
    seen: set[tuple[str, str, str, str]] = set()
    # 1) Из users.db (историческая таблица)
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT day, start, end, kind, target FROM teacher_lessons WHERE tg_id=? AND day BETWEEN ? AND ?",
                (tg_id, days[0], days[-1])
            )
            for d, s, e, k, t in cur.fetchall():
                try:
                    day_dt = dt.datetime.strptime(d, "%Y-%m-%d")
                except Exception:
                    continue
                label = _label_for(day_dt)
                # Преобразуем в формат событий
                try:
                    sh, sm = map(int, (s or "00:00").split(":", 1))
                    eh, em = map(int, (e or "00:00").split(":", 1))
                except Exception:
                    sh, sm, eh, em = 0, 0, 0, 0
                start_dt = dt.datetime.combine(day_dt.date(), dt.time(sh, sm))
                end_dt = dt.datetime.combine(day_dt.date(), dt.time(eh, em))
                title = ("Урок: " + (t or "")) if k == "student" else ("Группа: " + (t or ""))
                sig = (label, start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M"), title)
                if sig in seen:
                    continue
                seen.add(sig)
                by_label.setdefault(label, []).append({
                    "start": start_dt,
                    "end": end_dt,
                    "title": title,
                })
    except Exception:
        pass

    # 2) Плюс локальный календарь per-teacher из CALENDAR_DB
    try:
        from .teachers import get_teacher_moniker  # локальный импорт, избежание циклов
        moniker = get_teacher_moniker(tg_id) or f"teacher_{tg_id}"
        _ensure_calendar_table(moniker)
        table = _safe_table_name(moniker)
        with sqlite3.connect(CALENDAR_DB) as conn2:
            cur2 = conn2.cursor()
            cur2.execute(
                f"SELECT day, start, end, kind, target FROM {table} WHERE day BETWEEN ? AND ?",
                (days[0], days[-1])
            )
            for d, s, e, k, t in cur2.fetchall():
                try:
                    day_dt = dt.datetime.strptime(d, "%Y-%m-%d")
                except Exception:
                    continue
                label = _label_for(day_dt)
                try:
                    sh, sm = map(int, (s or "00:00").split(":", 1))
                    eh, em = map(int, (e or "00:00").split(":", 1))
                except Exception:
                    sh, sm, eh, em = 0, 0, 0, 0
                start_dt = dt.datetime.combine(day_dt.date(), dt.time(sh, sm))
                end_dt = dt.datetime.combine(day_dt.date(), dt.time(eh, em))
                title = ("Урок: " + (t or "")) if k == "student" else ("Группа: " + (t or ""))
                sig = (label, start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M"), title)
                if sig in seen:
                    continue
                seen.add(sig)
                by_label.setdefault(label, []).append({
                    "start": start_dt,
                    "end": end_dt,
                    "title": title,
                })
    except Exception:
        pass

    return by_label



def get_lesson_by_id(lesson_id: int) -> Optional[Dict]:
    """Возвращает запись урока по id или None."""
    _ensure_table()
    with sqlite3.connect(USERS_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, tg_id, day, start, end, kind, target, COALESCE(notify_before_min,30) FROM teacher_lessons WHERE id=?",
            (lesson_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "tg_id": int(row[1]),
        "day": str(row[2]),
        "start": str(row[3]),
        "end": str(row[4]),
        "kind": str(row[5]),
        "target": str(row[6]),
        "notify_before_min": int(row[7] or 30),
    }


def update_lesson_notify_minutes(lesson_id: int, minutes: int) -> bool:
    """Обновляет поле notify_before_min в обеих БД. Возвращает True, если удалось где-либо."""
    minutes = int(minutes)
    if minutes < 0:
        minutes = 0
    ok1 = False
    ok2 = False
    try:
        with sqlite3.connect(USERS_DB) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE teacher_lessons SET notify_before_min=? WHERE id=?", (minutes, int(lesson_id)))
            conn.commit()
            ok1 = cur.rowcount > 0
    except Exception:
        ok1 = False

    try:
        with sqlite3.connect(CALENDAR_DB) as conn2:
            cur2 = conn2.cursor()
            cur2.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cal_%'")
            for (tbl,) in cur2.fetchall():
                try:
                    cur2.execute(f"UPDATE {tbl} SET notify_before_min=? WHERE id=?", (minutes, int(lesson_id)))
                    if cur2.rowcount:
                        ok2 = True
                except Exception:
                    continue
            conn2.commit()
    except Exception:
        ok2 = ok2 or False
    return ok1 or ok2

