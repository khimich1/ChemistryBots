import os
import base64
import logging
from io import BytesIO
from typing import Tuple, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai import PermissionDeniedError, APIConnectionError, RateLimitError, APIStatusError

load_dotenv()

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Системные правила для анализа изображений
TASK_ANALYSIS_SYSTEM_RULES: str = r"""
Ты — эксперт по анализу изображений с химическими задачами и конспектами.

Твоя задача — определить, что изображено на фото:

1. ЗАДАЧА - если видишь:
   - Вопрос или задание по химии
   - Химические уравнения для решения
   - Числовые данные для расчётов
   - Слова "найти", "вычислить", "определить", "рассчитать"
   - Условия задачи с данными

2. КОНСПЕКТ - если видишь:
   - Записанные от руки или печатные заметки
   - Теоретический материал
   - Определения, формулы без заданий
   - Лекционные записи

3. НЕ ОПРЕДЕЛЕНО - если:
   - Изображение неразборчиво
   - Нет химического контента
   - Пустая страница

Ответь ТОЛЬКО одним словом: "ЗАДАЧА", "КОНСПЕКТ" или "НЕ_ОПРЕДЕЛЕНО"
"""

# Системные правила для решения задач
TASK_SOLVER_SYSTEM_RULES: str = r"""
Ты — опытный преподаватель химии. Решай задачи пошагово с подробными объяснениями.

ПРАВИЛА:
1. НИКОГДА не изменяй условия задачи - решай точно то, что дано
2. Не добавляй свои данные или условия
3. Если данных недостаточно - укажи это
4. Объясняй каждый шаг простыми словами
5. Используй химические формулы и уравнения
6. Показывай расчёты
7. Давай чёткий ответ

ФОРМАТ ОТВЕТА:
📋 Условие задачи:
[перепиши условие точно]

🔍 Анализ:
[что нужно найти, какие данные есть]

📝 Решение:
[пошаговое решение с объяснениями]

✅ Ответ:
[конкретный ответ с единицами измерения]

💡 Объяснение:
[почему именно такой ответ]

ОФОРМЛЕНИЕ:
— Делай короткие абзацы (максимум 3–4 строки).
— Формулы и химические реакции выделяй отдельно, в отдельной строке, между пустыми строками.
— Формулы пиши в моноширинном стиле: обрами их тройными обратными кавычками (```).
— НЕ используй LaTeX-форматирование (\text{}, \xrightarrow{} и т.д.) - пиши формулы простым текстом.
— Примеры правильного оформления формул:
  ```
  Fe2O3 + 3H2 = 2Fe + 3H2O
  ```
  ```
  Fe2(SO4)3 + FeSO4
  ```
— Важные мысли отмечай эмодзи, например: 📌, 🔥, ⚡️, 💡.
— Не делай простыню — разбивай объяснение на блоки: определение, пример, вывод, реакция.
— Если встречаются сложные термины — объясняй их простым языком.
"""

# Системные правила для распознавания конспектов
CONSPECT_OCR_SYSTEM_RULES: str = r"""
Ты — ассистент по точной транскрипции конспектов. ВАЖНО: выполняй ИСКЛЮЧИТЕЛЬНО ТОЧНУЮ
ПЕРЕПИСКУ символов с изображения, особенно для химических формул и уравнений. НИКОГДА
не исправляй, не доделывай и не переформулируй формулы и коэффициенты. Если символ
неразборчив — поставь знак вопроса (?) на его месте.

ОФОРМЛЕНИЕ:
— Делай короткие абзацы (максимум 3–4 строки).
— Все химические формулы и уравнения выводи КАК ЕСТЬ, в отдельной строке, в код-блоке (```),
без каких‑либо правок. Сохраняй регистр букв, дефисы, стрелки (→ или ->), знаки заряда,
индексы и коэффициенты ровно как на фото.
— Не добавляй поясняющих предложений внутри код-блоков с формулами.
— После формул можешь кратко оформить текст конспекта обычными абзацами.
"""


async def analyze_image_content(image_bytes: bytes) -> str:
    """Определить тип контента на изображении: задача, конспект или не определено."""
    try:
        data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
        user_content = [
            {"type": "text", "text": "Проанализируй изображение и определи тип контента."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        resp = await client.chat.completions.create(
            model=os.getenv("LLM_VISION_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": TASK_ANALYSIS_SYSTEM_RULES},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
        )
        result = (resp.choices[0].message.content or "").strip().upper()
        
        # Нормализация ответа
        if "ЗАДАЧА" in result:
            return "ЗАДАЧА"
        elif "КОНСПЕКТ" in result:
            return "КОНСПЕКТ"
        else:
            return "НЕ_ОПРЕДЕЛЕНО"
            
    except Exception as e:
        logger.error("[ANALYSIS ERROR] analyze_image_content: %s", e, exc_info=True)
        return "НЕ_ОПРЕДЕЛЕНО"


async def solve_chemistry_task(image_bytes: bytes) -> str:
    """Решить химическую задачу с подробным объяснением."""
    try:
        data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
        user_content = [
            {"type": "text", "text": "Реши эту химическую задачу пошагово с подробными объяснениями."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        resp = await client.chat.completions.create(
            model=os.getenv("LLM_VISION_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": TASK_SOLVER_SYSTEM_RULES},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
        
    except PermissionDeniedError as e:
        logger.error("[LLM ERROR] solve_chemistry_task: %s", e, exc_info=True)
        return "Сейчас решение задач недоступно (ограничение сервиса). Попробуйте чуть позже."
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        logger.error("[LLM ERROR] solve_chemistry_task: %s", e, exc_info=True)
        return "Сейчас решение задач недоступно (проблема сети). Попробуйте чуть позже."
    except Exception as e:
        logger.error("[SOLVER ERROR] solve_chemistry_task: %s", e, exc_info=True)
        return "Произошла ошибка при решении задачи. Попробуйте ещё раз."


async def recognize_conspect_text(image_bytes: bytes) -> str:
    """Распознать текст конспекта с точным сохранением формул."""
    try:
        data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
        user_content = [
            {"type": "text", "text": "Распознай и оформи конспект по правилам выше."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        resp = await client.chat.completions.create(
            model=os.getenv("LLM_VISION_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": CONSPECT_OCR_SYSTEM_RULES},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()
        
    except PermissionDeniedError as e:
        logger.error("[LLM ERROR] recognize_conspect_text: %s", e, exc_info=True)
        return "Сейчас распознавание недоступно (ограничение сервиса). Попробуйте чуть позже."
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        logger.error("[LLM ERROR] recognize_conspect_text: %s", e, exc_info=True)
        return "Сейчас распознавание недоступно (проблема сети). Попробуйте чуть позже."
    except Exception as e:
        logger.error("[OCR ERROR] recognize_conspect_text: %s", e, exc_info=True)
        return ""


async def solve_text_task(task_text: str) -> str:
    """Решить химическую задачу, отправленную текстом."""
    try:
        prompt = f"Реши эту химическую задачу пошагово с подробными объяснениями:\n\n{task_text}"
        
        resp = await client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": TASK_SOLVER_SYSTEM_RULES},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
        
    except PermissionDeniedError as e:
        logger.error("[LLM ERROR] solve_text_task: %s", e, exc_info=True)
        return "Сейчас решение задач недоступно (ограничение сервиса). Попробуйте чуть позже."
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        logger.error("[LLM ERROR] solve_text_task: %s", e, exc_info=True)
        return "Сейчас решение задач недоступно (проблема сети). Попробуйте чуть позже."
    except Exception as e:
        logger.error("[SOLVER ERROR] solve_text_task: %s", e, exc_info=True)
        return "Произошла ошибка при решении задачи. Попробуйте ещё раз."


async def is_chemistry_task(text: str) -> bool:
    """Определить, является ли текст химической задачей."""
    try:
        prompt = f"""Определи, является ли этот текст химической задачей:

{text}

Химическая задача содержит:
- Вопрос или задание по химии
- Химические уравнения для решения
- Числовые данные для расчётов
- Слова "найти", "вычислить", "определить", "рассчитать"
- Условия задачи с данными

Ответь ТОЛЬКО "ДА" или "НЕТ"."""

        resp = await client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": "Ты — эксперт по определению химических задач. Отвечай только ДА или НЕТ."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        result = (resp.choices[0].message.content or "").strip().upper()
        return "ДА" in result or "YES" in result
        
    except Exception as e:
        logger.error("[ANALYSIS ERROR] is_chemistry_task: %s", e, exc_info=True)
        return False


async def process_image_for_task_or_conspect(image_bytes: bytes) -> Tuple[str, str]:
    """
    Обработать изображение: определить тип контента и вернуть результат.
    
    Returns:
        Tuple[str, str]: (тип_контента, результат_обработки)
    """
    # Сначала определяем тип контента
    content_type = await analyze_image_content(image_bytes)
    
    if content_type == "ЗАДАЧА":
        solution = await solve_chemistry_task(image_bytes)
        return "ЗАДАЧА", solution
    elif content_type == "КОНСПЕКТ":
        text = await recognize_conspect_text(image_bytes)
        return "КОНСПЕКТ", text
    else:
        return "НЕ_ОПРЕДЕЛЕНО", (
            "🔍 Не удалось определить содержимое изображения.\n\n"
            "Эта функция работает по-другому:\n"
            "• 📝 Для решения задач — отправьте фото с химической задачей\n"
            "• 📸 Для распознавания конспектов — отправьте фото с рукописными заметками\n\n"
            "⚠️ Важно: в заданиях и конспектах категорически нельзя ничего менять или добавлять!"
        )
