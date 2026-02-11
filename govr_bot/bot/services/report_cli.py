import argparse
import os
import sys
from pathlib import Path

# Добавляем путь к модулю в parent_bot
parent_services_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "parent_bot", "bot", "services")
sys.path.insert(0, parent_services_path)

from . import pdf_generator as pg
from filename_generator import get_filename_for_user, get_user_display_name


def main():
    parser = argparse.ArgumentParser(description="Generate student report PDF (govr_bot)")
    parser.add_argument("--user-id", type=int, required=True, help="Telegram user_id of student")
    parser.add_argument("--output", type=str, default="", help="Output PDF path (optional)")
    parser.add_argument("--fallback-name", type=str, default="", help="Fallback full name if DB empty")
    args = parser.parse_args()

    user_id = int(args.user_id)
    fallback = (args.fallback_name or "").strip() or None

    # Генерируем имя файла с использованием общего модуля
    if args.output.strip():
        out_path = str(Path(args.output.strip()).resolve())
    else:
        filename = get_filename_for_user(user_id, fallback, None)
        out_path = str(Path(filename).resolve())

    # Получаем отображаемое имя пользователя
    display_name = get_user_display_name(user_id, fallback, None)

    # Build PDF using govr generator. Records are optional; pass empty list
    pg.make_report(user_id, display_name, records=[], filename=out_path)
    print(out_path)


if __name__ == "__main__":
    main()


