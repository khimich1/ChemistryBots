import asyncio
import os
import sqlite3
import sys

from aiogram import Bot

# Локальные импорты из проекта
from prepod_bot.config import DB_PATH  # type: ignore
from prepod_bot.services.groups import get_work_group_members  # type: ignore


def _pick_govr_token() -> str | None:
    token = (
        os.getenv("BOT_TOKEN_govor")
        or os.getenv("BOT_TOKEN_GOVOR")
        or os.getenv("BOT_TOKEN_govr")
        or os.getenv("BOT_TOKEN_GOVR")
        or os.getenv("GOVR_BOT_TOKEN")
        or os.getenv("BOT_TOKEN")
    )
    if token:
        return token
    # Попробуем прочитать .env из govr_bot
    try:
        from dotenv import dotenv_values
        repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        env_path = os.path.join(repo_root, "govr_bot", ".env")
        if os.path.exists(env_path):
            vals = dotenv_values(env_path)
            return (
                vals.get("BOT_TOKEN_govor")
                or vals.get("BOT_TOKEN_GOVOR")
                or vals.get("BOT_TOKEN")
            )
    except Exception:
        pass
    return None


async def diagnose(group_no: int) -> int:
    print(f"Группа: {group_no}")
    user_ids = get_work_group_members(group_no)
    if not user_ids:
        print("В группе нет участников")
        return 1
    print(f"Участники: {user_ids}")

    # 1) Кто отсутствует в базе test_answers prepod_bot — такие в рассылке считаются ошибками
    missing_in_answers: list[int] = []
    present_in_answers: list[int] = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            for uid in user_ids:
                cur.execute("SELECT 1 FROM test_answers WHERE user_id=? LIMIT 1", (uid,))
                if cur.fetchone():
                    present_in_answers.append(uid)
                else:
                    missing_in_answers.append(uid)
    except Exception as e:
        print(f"Ошибка доступа к БД {DB_PATH}: {e}")
        return 2

    print(f"Нет записей в test_answers: {missing_in_answers}")

    # 2) Проверим доступность пользователей для govr-бота (не отправляя текст) — action 'typing'
    token = _pick_govr_token()
    if not token:
        print("Токен govr-бота не найден. Проверьте переменные окружения или govr_bot/.env")
        return 3

    bot = Bot(token=token)
    ok: list[int] = []
    tg_errors: list[tuple[int, str]] = []
    for uid in present_in_answers:
        try:
            await bot.send_chat_action(uid, "typing")
            ok.append(uid)
        except Exception as e:
            tg_errors.append((uid, str(e)))
    try:
        await bot.session.close()
    except Exception:
        pass

    print(f"Доступны (OK): {ok}")
    if tg_errors:
        print("Ошибки Telegram (обычно пользователь не писал govr-боту/заблокировал):")
        for uid, err in tg_errors:
            print(f"  - {uid}: {err}")
    else:
        print("Ошибок Telegram нет")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python -m prepod_bot.scripts.diagnose_broadcast <group_no>")
        sys.exit(1)
    try:
        grp = int(sys.argv[1])
    except Exception:
        print("Номер группы должен быть целым")
        sys.exit(1)
    rc = asyncio.run(diagnose(grp))
    sys.exit(rc)





