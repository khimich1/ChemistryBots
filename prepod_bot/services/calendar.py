import datetime as dt
from typing import List, Dict, Tuple

import httpx


def _iso_week_range(base_date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """Возвращает границы недели (понедельник 00:00:00 — воскресенье 23:59:59)."""
    weekday = base_date.isoweekday()  # 1..7 (Mon..Sun)
    start_date = base_date - dt.timedelta(days=weekday - 1)
    start = dt.datetime.combine(start_date, dt.time.min)
    end = start + dt.timedelta(days=6, hours=23, minutes=59, seconds=59)
    return start, end


def _parse_ical(content: str) -> List[Dict]:
    """
    Очень простой парсер .ics: выдёргивает DTSTART, DTEND, SUMMARY.
    Поддерживает строки формата YYYYMMDD или YYYYMMDDTHHMMSSZ.
    Без зависимостей, чтобы не утяжелять проект.
    """
    events: List[Dict] = []
    cur: Dict[str, str] | None = None
    for line in content.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None:
            if line.startswith("DTSTART"):
                _, value = line.split(":", 1)
                cur["DTSTART"] = value
            elif line.startswith("DTEND"):
                _, value = line.split(":", 1)
                cur["DTEND"] = value
            elif line.startswith("SUMMARY"):
                _, value = line.split(":", 1)
                cur["SUMMARY"] = value

    def _parse_dt(value: str) -> dt.datetime | None:
        value = (value or "").strip()
        formats = ["%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"]
        for fmt in formats:
            try:
                d = dt.datetime.strptime(value, fmt)
                # Если дата без времени — считаем 00:00
                if fmt == "%Y%m%d":
                    return dt.datetime(d.year, d.month, d.day, 0, 0, 0)
                return d
            except Exception:
                continue
        return None

    normalized: List[Dict] = []
    for ev in events:
        start = _parse_dt(ev.get("DTSTART", ""))
        end = _parse_dt(ev.get("DTEND", ""))
        if not start:
            continue
        if not end:
            end = start + dt.timedelta(hours=1)
        title = (ev.get("SUMMARY") or "Событие").strip()
        normalized.append({
            "start": start,
            "end": end,
            "title": title,
        })
    return normalized


async def fetch_week_events(ical_url: str, *, base_date: dt.date | None = None, timeout_s: float = 10.0) -> Tuple[List[Dict], Tuple[dt.datetime, dt.datetime]]:
    """
    Скачивает .ics по ссылке и возвращает события текущей недели.
    Возвращает список словарей {start: datetime, end: datetime, title: str} отсортированный по времени.
    """
    base_date = base_date or dt.date.today()
    week_start, week_end = _iso_week_range(base_date)

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.get(ical_url)
        resp.raise_for_status()
        content = resp.text

    all_events = _parse_ical(content)
    in_week: List[Dict] = []
    for ev in all_events:
        start = ev["start"]
        end = ev["end"]
        if end < week_start or start > week_end:
            continue
        in_week.append(ev)

    in_week.sort(key=lambda e: e["start"]) 
    return in_week, (week_start, week_end)


def format_events_week(events: List[Dict], *, week_bounds: Tuple[dt.datetime, dt.datetime], extra_per_day: Dict[str, List[Dict]] | None = None) -> str:
    """Форматирует список событий недели в удобный для Telegram текст."""
    start, end = week_bounds
    by_day: dict[str, List[Dict]] = {}
    # Инициализируем все дни недели, даже если пустые
    cur = start
    for i in range(7):
        label = cur.strftime("%a, %d.%m")
        by_day[label] = []
        cur = cur + dt.timedelta(days=1)

    # Добавим ICS события
    for ev in events:
        label = ev["start"].strftime("%a, %d.%m")
        by_day.setdefault(label, []).append(ev)

    # Добавим доп.события (уроки), если переданы
    extra_per_day = extra_per_day or {}
    for label, extras in extra_per_day.items():
        for ev in extras:
            by_day.setdefault(label, []).append(ev)

    # Форматируем
    lines: List[str] = []
    # Сортировка по датам через итерирование от start до end
    cur_date = start
    for _ in range(7):
        day_label = cur_date.strftime("%a, %d.%m")
        lines.append(f"📅 {day_label}")
        day_events = sorted(by_day.get(day_label, []), key=lambda e: e.get("start") or dt.datetime.combine(cur_date.date(), dt.time(0,0)))
        if not day_events:
            lines.append("  • —")
        else:
            for ev in day_events:
                s = ev.get("start")
                e = ev.get("end")
                t1 = s.strftime("%H:%M") if isinstance(s, dt.datetime) else "--:--"
                t2 = e.strftime("%H:%M") if isinstance(e, dt.datetime) else "--:--"
                title = ev.get("title") or "Событие"
                lines.append(f"  • {t1}-{t2} — {title}")
        lines.append("")
        cur_date = cur_date + dt.timedelta(days=1)
    return "\n".join(lines).strip()


