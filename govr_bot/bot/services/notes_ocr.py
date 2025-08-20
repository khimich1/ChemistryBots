import os
import base64
import logging
from io import BytesIO

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai import PermissionDeniedError, APIConnectionError, RateLimitError, APIStatusError

# Лёгкая предобработка фото для рукописей
try:
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

load_dotenv()

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Правила оформления распознанного конспекта (для масштабирования держим отдельно)
NOTES_OCR_SYSTEM_RULES: str = (
    "Ты — ассистент по точной транскрипции конспектов. ВАЖНО: выполняй ИСКЛЮЧИТЕЛЬНО ТОЧНУЮ"
    " ПЕРЕПИСКУ символов с изображения, особенно для химических формул и уравнений. НИКОГДА"
    " не исправляй, не доделывай и не переформулируй формулы и коэффициенты. Если символ"
    " неразборчив — поставь знак вопроса (?) на его месте.\n\n"
    "ОФОРМЛЕНИЕ:"
    "— Делай короткие абзацы (максимум 3–4 строки)."
    "— Все химические формулы и уравнения выводи КАК ЕСТЬ, в отдельной строке, в код-блоке (```),"
    " без каких‑либо правок. Сохраняй регистр букв, дефисы, стрелки (→ или ->), знаки заряда,"
    " индексы и коэффициенты ровно как на фото."
    "— Не добавляй поясняющих предложений внутри код-блоков с формулами."
    "— После формул можешь кратко оформить текст конспекта обычными абзацами."
)


def _preprocess_handwritten_image(image_bytes: bytes) -> bytes:
    """Усилить читаемость рукописного фото: масштаб, контраст, резкость, автоконтраст.

    Возвращает байты PNG. Если Pillow недоступен, вернёт исходные байты.
    """
    if not _PIL_AVAILABLE:
        return image_bytes

    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img = img.convert("L")  # градации серого

            # Масштабирование для мелких почерков (до ~1.5x, но не более 2200 px по длинной стороне)
            width, height = img.size
            long_side = max(width, height)
            scale = 1.5 if long_side < 1500 else 1.0
            if scale != 1.0:
                img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)

            # Автоконтраст и лёгкое повышение контраста/резкости
            img = ImageOps.autocontrast(img, cutoff=1)
            img = ImageEnhance.Contrast(img).enhance(1.4)
            img = ImageFilter.UnsharpMask(radius=2, percent=160)

            # Сохранение в PNG (без потерь)
            out = BytesIO()
            img.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception:
        return image_bytes


async def recognize_notes_from_image(image_bytes: bytes) -> str:
    """Распознать текст с фото конспекта и оформить по правилам.

    Возвращает чистый Telegram‑текст. В случае недоступности LLM — лаконичное сообщение для пользователя.
    """
    try:
        # Предобработка для лучшей читаемости рукописей
        enhanced = _preprocess_handwritten_image(image_bytes)
        mime = "image/png" if enhanced != image_bytes else "image/jpeg"
        data_url = "data:" + mime + ";base64," + base64.b64encode(enhanced).decode("ascii")
        user_content = [
            {"type": "text", "text": "Распознай и оформи конспект по правилам выше."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        resp = await client.chat.completions.create(
            # Для лучшей точности используем более сильную модель по умолчанию
            model=os.getenv("LLM_VISION_MODEL", "gpt-4o"),
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


