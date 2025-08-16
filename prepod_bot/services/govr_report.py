import os
import sys
from typing import Optional


def _ensure_govr_on_path() -> str:
    """Добавляет папку govr_bot в sys.path и возвращает её путь."""
    this_dir = os.path.dirname(__file__)  # .../prepod_bot/services
    repo_root = os.path.normpath(os.path.join(this_dir, "..", ".."))
    govr_dir = os.path.join(repo_root, "govr_bot")
    if govr_dir not in sys.path:
        sys.path.insert(0, govr_dir)
    return govr_dir


def make_pdf_report(user_id: int, fullname: Optional[str], filename: str) -> str:
    """
    Обёртка над govr_bot/bot/services/pdf_generator.make_report.
    records не используем — передаём пустой список, чтобы отчёт строился без Google Sheets.
    """
    _ensure_govr_on_path()
    # Импортируем после настройки sys.path
    from bot.services.pdf_generator import make_report as govr_make_report  # type: ignore

    # В оригинальном модуле сигнатура: (user_id, fullname, records, filename)
    records: list[dict] = []
    return govr_make_report(user_id, fullname or "", records, filename)


