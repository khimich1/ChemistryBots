import os
import base64
import logging

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai import PermissionDeniedError, APIConnectionError, RateLimitError, APIStatusError

load_dotenv()

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Правила оформления распознанного конспекта (для масштабирования держим отдельно)
NOTES_OCR_SYSTEM_RULES: str = (
    "Ты — ассистент‑верстальщик учебных конспектов. Аккуратно распознай текст с фото "
    "и верни его в виде удобного сообщения для Telegram, без приветствий и лишних фраз.\n\n"
    "ОФОРМЛЕНИЕ:"
    "— Делай короткие абзацы (максимум 3–4 строки)."
    "— Формулы и химические реакции выделяй отдельно, в отдельной строке, между пустыми строками."
    "— Формулы пиши в моноширинном стиле: обрами их тройными обратными кавычками (``` )."
    "— Важные мысли отмечай эмодзи, например: 📌, 🔥, ⚡️, 💡."
    "— Не делай простыню — разбивай объяснение на блоки: определение, пример, вывод, реакция."
    "— Если встречаются сложные термины — объясняй их простым языком."
)


async def recognize_notes_from_image(image_bytes: bytes) -> str:
    """Распознать текст с фото конспекта и оформить по правилам.

    Возвращает чистый Telegram‑текст. В случае недоступности LLM — лаконичное сообщение для пользователя.
    """
    try:
        data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
        user_content = [
            {"type": "text", "text": "Распознай и оформи конспект по правилам выше."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        resp = await client.chat.completions.create(
            model=os.getenv("LLM_VISION_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": NOTES_OCR_SYSTEM_RULES},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()
    except PermissionDeniedError as e:
        logger.error("[LLM ERROR] notes_ocr: %s", e, exc_info=True)
        return (
            "Сейчас распознавание недоступно (ограничение сервиса). Попробуйте чуть позже."
        )
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        logger.error("[LLM ERROR] notes_ocr: %s", e, exc_info=True)
        return (
            "Сейчас распознавание недоступно (проблема сети). Попробуйте чуть позже."
        )
    except Exception as e:
        logger.error("[OCR ERROR] notes_ocr: %s", e, exc_info=True)
        return ""


