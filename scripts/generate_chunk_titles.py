import os
import sqlite3
import asyncio

# Запускается из корня проекта. Ищем модули по относительным путям
import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
GOVR_ROOT = os.path.join(PROJECT_ROOT, "govr_bot")
if GOVR_ROOT not in sys.path:
    sys.path.insert(0, GOVR_ROOT)

from govr_bot.bot.utils import (
    PREPARED_LECTURES_DB,
    ensure_chunk_title_column,
    get_prepared_lecture,
    set_chunk_title,
)
from govr_bot.bot.services.gpt_service import generate_chunk_title


async def main() -> None:
    ensure_chunk_title_column()
    total_done = 0
    total_skipped = 0

    with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
        c = conn.cursor()
        # Узнаём доступные темы и индексы частей
        c.execute("SELECT DISTINCT topic FROM prepared_lectures ORDER BY topic")
        topics = [row[0] for row in c.fetchall() if row and row[0]]

        for topic in topics:
            # Для каждой темы возьмём все chunk_idx и текущие заголовки
            c.execute(
                "SELECT chunk_idx, COALESCE(NULLIF(TRIM(chunk_title), ''), NULL) FROM prepared_lectures WHERE topic=? ORDER BY chunk_idx",
                (topic,),
            )
            rows = c.fetchall()
            print(f"\n=== {topic} ===")
            for ch_idx, title in rows:
                if title:
                    total_skipped += 1
                    print(f"[{ch_idx}] уже есть: {title}")
                    continue

                text = get_prepared_lecture(topic, ch_idx)
                if not text:
                    print(f"[{ch_idx}] нет текста — пропуск")
                    total_skipped += 1
                    continue

                print(f"[{ch_idx}] генерирую…", end=" ")
                new_title = await generate_chunk_title(topic, text)
                if new_title:
                    set_chunk_title(topic, ch_idx, new_title)
                    print(f"OK: {new_title}")
                    total_done += 1
                else:
                    print("пропуск (LLM)")
                    total_skipped += 1

    print("\nГотово.")
    print(f"Новых заголовков записано: {total_done}")
    print(f"Пропущено: {total_skipped}")


if __name__ == "__main__":
    asyncio.run(main())


