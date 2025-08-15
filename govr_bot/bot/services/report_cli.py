import argparse
import os
from pathlib import Path

from . import pdf_generator as pg


def main():
    parser = argparse.ArgumentParser(description="Generate student report PDF (govr_bot)")
    parser.add_argument("--user-id", type=int, required=True, help="Telegram user_id of student")
    parser.add_argument("--output", type=str, default="", help="Output PDF path (optional)")
    parser.add_argument("--fallback-name", type=str, default="", help="Fallback full name if DB empty")
    args = parser.parse_args()

    user_id = int(args.user_id)
    fallback = (args.fallback_name or "").strip() or None

    # Resolve destination path
    out_path = args.output.strip()
    if not out_path:
        out_path = f"report_{user_id}.pdf"
    out_path = str(Path(out_path).resolve())

    # Pick full name from DB (or fallback)
    try:
        full_name = pg._get_full_name_for_report(user_id, fallback_fullname=fallback)  # noqa: SLF001
    except Exception:
        full_name = fallback or "Ученик"

    # Build PDF using govr generator. Records are optional; pass empty list
    pg.make_report(user_id, full_name, records=[], filename=out_path)
    print(out_path)


if __name__ == "__main__":
    main()


