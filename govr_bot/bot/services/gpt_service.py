import os
import logging
import asyncio
from typing import List

from openai import AsyncOpenAI
from openai import PermissionDeniedError, APIConnectionError, RateLimitError, APIStatusError
from bot.utils import (
    TEXTBOOK_CONTENT,
    get_prepared_chunks_count,
    get_prepared_lecture,
)
import httpx
from pydub import AudioSegment
from dotenv import load_dotenv  # Для .env

# 1. Загружаем переменные из .env
load_dotenv()
# 2. Создаём асинхронный клиент OpenAI (новый SDK 1.x)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Настройка ffmpeg для pydub (если нужно)
FFMPEG_BIN = os.getenv("FFMPEG_BINARY", "")
if FFMPEG_BIN:
    AudioSegment.converter = FFMPEG_BIN

# Логгер и ключ API
logger = logging.getLogger(__name__)


def _llm_unavailable_message() -> str:
    return (
        "Сейчас ответ ИИ недоступен (ограничение сервиса). "
        "Продолжай читать теорию и попробуй снова чуть позже."
    )


# Ранний вариант фолбэка на локальный конспект убран по просьбе пользователя.


def _log_llm_issue(where: str, error: Exception) -> None:
    """Лаконичное логирование с контекстом — видно в консоли.

    where: короткая метка места вызова (например, 'answer_student_question').
    error: исключение, полученное от SDK/сети.
    """
    logger.error("[LLM ERROR] %s: %s: %s", where, type(error).__name__, error, exc_info=True)


# Порог принятия ответа по оценке модели (0..1). Можно переопределить через env LLM_GRADE_THRESHOLD
GRADE_THRESHOLD: float = 0.85
try:
    GRADE_THRESHOLD = float(os.getenv("LLM_GRADE_THRESHOLD", "0.85"))
except Exception:
    GRADE_THRESHOLD = 0.85


async def classify_topic(transcript: str) -> str:
    """
    Определить тему ответа ученика на основе его текста.
    """
    prompt = (
        "Определи тему по органической химии из этого ответа:\n\n"
        f"{transcript}"
    )
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        topic = resp.choices[0].message.content.strip().capitalize()
        logger.info(f"📚 Тема определена: {topic}")
        return topic
    except PermissionDeniedError as e:
        _log_llm_issue("classify_topic", e)
        return ""
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        _log_llm_issue("classify_topic", e)
        return ""


async def analyze_answer(
    transcript: str,
    topic: str,
    textbook_context: str
) -> str:
    """
    Проанализировать ответ ученика, сверив его с текстом учебника:
    сильные стороны, ошибки, несоответствия.
    """
    prompt = (
        f"У тебя есть текст учебника по теме «{topic}»:\n\n"
        f"{textbook_context}\n\n"
        f"Ученик дал такой ответ:\n\"{transcript}\"\n\n"
        "Сверь этот ответ с учебником: отметь, где он точно повторил текст, "
        "где допустил неточности или упустил важное. Ответь тёплым комментарием от учителя."
    )
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        feedback = resp.choices[0].message.content.strip()
        logger.info("💬 Ответ ученику с учётом учебника сгенерирован")
        return feedback
    except PermissionDeniedError as e:
        _log_llm_issue("analyze_answer", e)
        return _llm_unavailable_message()
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        _log_llm_issue("analyze_answer", e)
        return _llm_unavailable_message()


async def _transcribe_chunk(file_bytes: bytes) -> str:
    """
    Транскрибирует один кусок аудио через Whisper API.
    """
    url = "https://api.openai.com/v1/audio/transcriptions"
    # Указываем таймауты connect/read/write/pool
    timeout = httpx.Timeout(connect=30.0, read=60.0, write=60.0, pool=60.0)
    files = {
        "file": ("chunk.ogg", file_bytes, "audio/ogg"),
        "model": (None, "whisper-1"),
        "response_format": (None, "text"),
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
            files=files
        )
        resp.raise_for_status()
        return resp.text.strip()


async def transcribe_audio(file_path: str) -> str:
    """
    Разбивает аудио на 60-секундные сегменты, транскрибирует каждый
    и возвращает объединённый текст.
    """
    logger.info(f"🔍 Начало транскрипции (с резкой на сегменты): {file_path}")

    audio = AudioSegment.from_file(file_path, format="ogg")
    duration_ms = len(audio)
    chunk_length_ms = 60 * 1000  # 60 секунд

    transcripts: List[str] = []
    for start in range(0, duration_ms, chunk_length_ms):
        end = min(start + chunk_length_ms, duration_ms)
        chunk = audio[start:end]
        buf = chunk.export(format="ogg")
        data = buf.read()
        buf.close()

        logger.info(f"  → Чанк {start//1000}-{end//1000}s, байт {len(data)}")
        try:
            txt = await _transcribe_chunk(data)
            transcripts.append(txt)
        except Exception as e:
            logger.warning(f"Ошибка при транскрипции чанка {start//1000}-{end//1000}: {e}")
            transcripts.append("")
        await asyncio.sleep(0.5)

    full = "\n".join(filter(None, transcripts))
    logger.info("✅ Полная транскрипция завершена")
    return full


async def teach_material(chunk: str) -> str:
    """
    Преобразует фрагмент учебника в компактную, связанную лекцию для Telegram, с красивым форматированием.
    """
    system = (
        "Ты — опытный преподаватель по органической химии."
        "Твоя задача — объяснять теорию простыми словами,,без приветствий, без сложных терминов, с примерами из жизни, как если бы рассказывал ученику на уроке."
        "Преобразуй данный фрагмент учебника в связную, логичную часть большой лекции по теме, для подготовки к ЕГЭ по химии, чтобы все части курса, прочитанные подряд, легко складывались в одно целое и не повторялись."
        "Пиши дружелюбно, последовательно, избегай длинных и сложных предложений."
        "Текст будет отправлен через Телеграм."
        ""
        "ОФОРМЛЕНИЕ:"
        "— Делай короткие абзацы (максимум 3–4 строки)."
        "— Формулы и химические реакции выделяй отдельно, в отдельной строке, между пустыми строками."
        "— Формулы пиши в моноширинном стиле: обрами их тройными обратными кавычками (```)."
        "— Важные мысли отмечай эмодзи, например: 📌, 🔥, ⚡, 💡."
        "— Не делай простыню — разбивай объяснение на блоки: определение, пример, вывод, реакция."
        "— Если встречаются сложные термины — объясняй их простым языком."
        "В конце спроси: Всё ли понятно? Если остались вопросы — обязательно спрашивай!"
    )

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": chunk},
            ],
            temperature=0.7,
        )
        lecture = resp.choices[0].message.content.strip()
        logger.info("🎓 Лекция от преподавателя сгенерирована")
        return lecture
    except PermissionDeniedError as e:
        _log_llm_issue("teach_material", e)
        return _llm_unavailable_message()
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        _log_llm_issue("teach_material", e)
        return _llm_unavailable_message()


async def answer_student_question(topic: str, question: str) -> str:
    """
    Роль: преподаватель по теме. Дать понятный, краткий ответ на вопрос ученика.
    """
    system = f"Ты — преподаватель по теме «{topic}». Отвечай очень понятно и коротко."
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": question},
            ],
            temperature=0.7,
        )
        ans = resp.choices[0].message.content.strip()
        logger.info("❓ Вопрос ученика обработан и ответ сгенерирован")
        return ans
    except PermissionDeniedError as e:
        _log_llm_issue("answer_student_question", e)
        return _llm_unavailable_message()
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        _log_llm_issue("answer_student_question", e)
        return _llm_unavailable_message()


async def grade_theory_answer(topic: str, question_text: str, student_answer: str, expected_answer: str) -> tuple[bool, str]:
    """
    Оценивает короткий ответ ученика по смыслу, сравнивая с образцом.
    Возвращает (is_correct, feedback). Использует компактную JSON-ответную схему.

    Политика проверки:
      - Учитываем синонимы и перефразирование.
      - Если ответ по смыслу верен, но короче или частично совпадает — считаем верным.
      - Если ответ противоречит образцу — неверно.
      - Пиши краткий фидбек (1–2 предложения), по-русски.
    """
    # Если нет ожидаемого ответа — считаем всё корректным по умолчанию
    if not expected_answer or not expected_answer.strip():
        return True, "Ответ принят."

    system = (
        "Ты эксперт‑проверяющий. Задача — оценить КРАТКИЙ ответ ученика по смыслу, допускай синонимы и формулы. "
        "Нормализуй обозначения: знаки минуса (−/–/-) к '-', римские числа I/II/III/IV/V/VI к 1..6, подстрочные индексы ₀..₉ к обычным, формулы и названия веществ как эквиваленты (например: SF6 ↔ шестифторид серы ↔ серный гексафторид). "
        "Сравнивай ключевые термины: если по сути совпадает — зачесть как верно. Старайся НЕ заваливать из‑за формулировки."
    )
    user = (
        f"Тема: {topic}\n"
        f"Вопрос: {question_text}\n"
        f"Ответ ученика: {student_answer}\n"
        f"Образец ответа: {expected_answer}\n\n"
        "Верни строго JSON с полями: {"
        "\"is_correct\": true|false, "
        "\"score\": number (0..1), "
        "\"reasoning\": string (кратко, почему так), "
        "\"normalized_user\": string, "
        "\"normalized_expected\": string, "
        "\"matched_terms\": string"
        "}"
    )
    try:
        resp = await client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        import json
        obj = json.loads(content)
        # Безопасные извлечения
        is_correct = bool(obj.get("is_correct", False))
        score = float(obj.get("score", 1.0 if is_correct else 0.0))
        reasoning = str(obj.get("reasoning", "Ответ обработан."))
        # Применяем наш локальный порог
        if not is_correct and score >= GRADE_THRESHOLD:
            is_correct = True
        return is_correct, reasoning
    except PermissionDeniedError as e:
        _log_llm_issue("grade_theory_answer", e)
        # Падать нельзя — используем простой фоллбэк
        pass
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        _log_llm_issue("grade_theory_answer", e)
        pass
    except Exception as e:
        _log_llm_issue("grade_theory_answer", e)
        # Фоллбэк — простая проверка подстроки/похожести
        import difflib
        def _norm(s: str) -> str:
            return " ".join((s or "").lower().strip().split())
        norm_user = _norm(student_answer)
        norm_exp = _norm(expected_answer)
        ratio = difflib.SequenceMatcher(None, norm_user, norm_exp).ratio() if norm_exp else 0.0
        ok = bool(norm_exp and (ratio >= 0.8 or norm_exp in norm_user))
        fb = "Ответ принят." if ok else f"Проверь ещё раз. Образец: {expected_answer}"
        return ok, fb


async def check_trivial_name_by_formula(formula: str, student_answer: str) -> tuple[bool, str]:
    """
    Фолбэк‑проверка ответа в режиме практики карточек через LLM.
    Вопрос: может ли такой текст быть корректным названием вещества с формулой formula?

    Возвращает (is_correct, reasoning).
    """
    try:
        prompt = (
            "Проверь, может ли данный текст быть корректным русским названием вещества "
            "по указанной химической формуле. Допускай различия в дефисах и пробелах, "
            "варианты числительных (четырёх/4‑х/тетра) и орфографию (ё/е). Отвечай строго JSON.\n\n"
            f"Формула: {formula}\n"
            f"Ответ: {student_answer}\n\n"
            "Верни JSON со структурой: {\"is_correct\": true|false, \"reason\": string}."
        )
        resp = await client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        import json as _json
        obj = _json.loads(resp.choices[0].message.content or "{}")
        ok = bool(obj.get("is_correct", False))
        reason = str(obj.get("reason", ""))
        return ok, reason
    except PermissionDeniedError:
        _log_llm_issue("check_trivial_name_by_formula", PermissionDeniedError("permission denied (region)"))
        return False, ""
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        _log_llm_issue("check_trivial_name_by_formula", e)
        return False, ""


async def generate_chunk_title(topic: str, chunk_text: str) -> str:
    """Генерирует очень короткое название для фрагмента теории.

    Требования к заголовку:
      - до 40 символов
      - по-русски
      - без кавычек и точки в конце
      - по смыслу отражает ключевую мысль фрагмента
    """
    system = (
        "Ты помощник-редактор учебника. Сформулируй очень короткий заголовок (до 40 символов) "
        "для части лекции по химии. Без кавычек и точки в конце."
    )
    user = (
        f"Тема главы: {topic}\n\n"
        "Текст части:\n" + (chunk_text or "") + "\n\n"
        "Верни только короткий заголовок, ничего больше."
    )
    try:
        resp = await client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        title = (resp.choices[0].message.content or "").strip()
        # Пост-обработка: уберём кавычки и конечную точку, урежем длину
        title = title.strip('"\'\u00ab\u00bb ').rstrip('.')
        if len(title) > 40:
            title = title[:40].rstrip()
        return title
    except PermissionDeniedError as e:
        _log_llm_issue("generate_chunk_title", e)
        return ""
    except (APIConnectionError, RateLimitError, APIStatusError) as e:
        _log_llm_issue("generate_chunk_title", e)
        return ""
    except Exception as e:
        _log_llm_issue("generate_chunk_title", e)
        return ""
    except Exception as e:
        _log_llm_issue("check_trivial_name_by_formula", e)
        return False, ""