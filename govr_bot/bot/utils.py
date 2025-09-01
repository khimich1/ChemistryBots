import os
import json
import re
from typing import Any
from dotenv import load_dotenv

load_dotenv()

# ====== Тестовые темы (режим "Темы") ======
ALL_TOPICS = [
    "Алканы", "Алкены", "Алкины", "Арены", "Спирты", "Фенол",
    "Альдегиды и кетоны", "Карбоновые кислоты и эфиры", "Амины",
    "Аминокислоты и белки", "Углеводы", "Применение орг веществ"
]

# ====== Режим "Изучение": загружаем порции из JSON ======
BASE_DIR = os.path.dirname(__file__)
TB_DIR = os.path.join(BASE_DIR, "textbooks")

LEARNING_TOPICS = [
    os.path.splitext(fname)[0]
    for fname in sorted(os.listdir(TB_DIR))
    if fname.lower().endswith(".json")
]

TEXTBOOK_CONTENT: dict[str, list[str]] = {}
for topic in LEARNING_TOPICS:
    path = os.path.join(TB_DIR, f"{topic}.json")
    with open(path, encoding="utf-8") as f:
        TEXTBOOK_CONTENT[topic] = json.load(f)

# ====== Состояния пользователей ======
user_learning_state: dict[int, dict[str, Any]] = {}
user_topics: dict[int, str] = {}

# Путь к базе подготовленных лекций (из .env PREPARED_LECTURES_DB),
# по умолчанию — репозиторный shared/prepared_lectures.db, а если его нет — локальный bot/prepared_lectures.db
REPO_ROOT = os.path.normpath(os.path.join(BASE_DIR, "..", "..", ".."))
_env_db = os.getenv("PREPARED_LECTURES_DB", "").strip()
if _env_db:
    PREPARED_LECTURES_DB = _env_db
else:
    shared_db = os.path.join(REPO_ROOT, "shared", "prepared_lectures.db")
    local_db = os.path.join(BASE_DIR, "prepared_lectures.db")
    PREPARED_LECTURES_DB = shared_db if os.path.exists(shared_db) else local_db


def clean_html(text: str) -> str:
    """
    Простая очистка HTML-тегов из ответов GPT.
    """
    text = text.replace("<p>", "").replace("</p>", "")
    text = text.replace("<br>", "\n")
    text = text.replace("<ul>", "").replace("</ul>", "")
    text = text.replace("<ol>", "").replace("</ol>", "")
    text = text.replace("<li>", "• ").replace("</li>", "\n")
    return re.sub(r"<.*?>", "", text)

# ====== Конвертация LaTeX- и инлайн-формул в Markdown code-block ======

# подстрочные цифры (₀₁₂…₉)
_SUBSCRIPT = {str(i): chr(0x2080 + i) for i in range(10)}
# надстрочные цифры и знаки (¹²³…⁹, ⁺, ⁻)
_SUPERSCRIPT = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '-': '⁻'
}

# Используем raw строку для docstring, чтобы backslashes не интерпретировались
# pylint: disable=use-xrange
r"""
latex_to_codeblock(text: str) -> str

Заменяет LaTeX-блоки (\[...\]) и инлайн-формулы ($...$)
на Markdown code-block'и с Unicode-формулами.

Особенности замены:
  - убирает \text{...}
  - _{n} или _n → подстрочные цифры (₀₁₂...)
  - ^{n} или ^n → надстрочные цифры (¹²³...)
  - любые \rightarrow, \to, \longrightarrow, \xrightarrow → стрелка →
  - \equiv → знак эквивалентности ≡
  - удаляет фигурные скобки и лишние слеши
"""

def latex_to_codeblock(text: str) -> str:
    def _convert(match: re.Match) -> str:
        frm = match.group(1)
        # убрать \text{...}
        frm = re.sub(r'\\text\{([^}]*)\}', r'\1', frm)
        # подстрочные индексы _{digits}
        frm = re.sub(
            r'_(?:\{)?(\d+)(?:\})?',
            lambda m: ''.join(_SUBSCRIPT.get(ch, ch) for ch in m.group(1)),
            frm,
        )
        # надстрочные ^{digits} или ^digit
        frm = re.sub(
            r'\^(?:\{)?([^}]+)(?:\})?',
            lambda m: ''.join(_SUPERSCRIPT.get(ch, ch) for ch in m.group(1)),
            frm,
        )
        # стрелки и эквивалентность
        frm = re.sub(r'\\(?:rightarrow|to|longrightarrow|xrightarrow)', '→', frm)
        frm = re.sub(r'\\equiv', '≡', frm)
        # удалить фигурные скобки и обратные слеши
        frm = frm.replace('{', '').replace('}', '')
        frm = frm.replace('\\,', '')
        frm = frm.strip()
        # обернуть в Markdown code-block
        return f"```\n{frm}\n```"

    # заменить блочные формулы \[ ... \]
    text = re.sub(r'\\\[([\s\S]*?)\\\]', _convert, text, flags=re.DOTALL)
    # заменить инлайн-формулы $ ... $
    text = re.sub(r'\$([^$]+)\$', _convert, text)
    return text


def get_prepared_lecture(topic, idx):
    """
    Получает готовую лекцию по теме и номеру chunk'а из базы данных.
    Возвращает текст лекции, либо None если такого нет.
    """
    import sqlite3

    with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT lecture FROM prepared_lectures WHERE topic=? AND chunk_idx=?",
            (topic, idx),
        )
        row = c.fetchone()
        return row[0] if row else None


def ensure_chunk_title_column() -> None:
    """Безопасно добавляет столбец chunk_title в prepared_lectures, если его нет."""
    import sqlite3
    try:
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            cols = {row[1] for row in c.execute("PRAGMA table_info(prepared_lectures)")}
            if "chunk_title" not in cols:
                            c.execute("ALTER TABLE prepared_lectures ADD COLUMN chunk_title TEXT")
            conn.commit()
    except (sqlite3.Error, OSError):
        pass


def get_chunk_title(topic: str, idx: int) -> str | None:
    """Возвращает сохранённый заголовок части или None."""
    import sqlite3
    try:
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            cols = {row[1] for row in c.execute("PRAGMA table_info(prepared_lectures)")}
            if "chunk_title" not in cols:
                return None
            c.execute(
                "SELECT chunk_title FROM prepared_lectures WHERE topic=? AND chunk_idx=?",
                (topic, int(idx)),
            )
            row = c.fetchone()
            return str(row[0]) if row and row[0] else None
    except (sqlite3.Error, OSError):
        return None


def set_chunk_title(topic: str, idx: int, title: str) -> None:
    """Сохраняет заголовок части (тихо игнорирует ошибки)."""
    import sqlite3
    try:
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            cols = {row[1] for row in c.execute("PRAGMA table_info(prepared_lectures)")}
            if "chunk_title" not in cols:
                try:
                    c.execute("ALTER TABLE prepared_lectURES ADD COLUMN chunk_title TEXT")
                except sqlite3.Error:
                    return
            c.execute(
                "UPDATE prepared_lectures SET chunk_title=? WHERE topic=? AND chunk_idx=?",
                (title, topic, int(idx)),
            )
            conn.commit()
    except (sqlite3.Error, OSError):
        pass


def get_qa_questions(topic: str, idx: int) -> list[str]:
    """
    Возвращает список вопросов для задания по теме и номеру фрагмента
    из столбца qa_questions таблицы prepared_lectures.

    Если столбца/данных нет — возвращает пустой список.
    Поддерживает формат JSON-списка либо простой текст с вопросами построчно/через маркеры.
    """
    import sqlite3
    import json as _json

    try:
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            # проверим наличие столбца, чтобы не падать на старой БД
            cols = {row[1] for row in c.execute("PRAGMA table_info(prepared_lectures)")}
            if "qa_questions" not in cols:
                return []

            c.execute(
                "SELECT qa_questions FROM prepared_lectures WHERE topic=? AND chunk_idx=?",
                (topic, idx),
            )
            row = c.fetchone()
            if not row or not row[0]:
                return []

            raw = row[0]
            # Попробуем как JSON
            try:
                data = _json.loads(raw)
                return [str(x).strip() for x in data if str(x).strip()]
            except (json.JSONDecodeError, TypeError):
                # Фоллбэк: разбить по строкам/маркерам
                lines = [ln.strip("- *\t ") for ln in str(raw).splitlines() if ln.strip()]
                return lines
    except (sqlite3.Error, OSError):
        return []


def get_total_questions_count_for_topic(topic: str) -> int:
    """
    Возвращает общее количество вопросов по всей теме (сумма по всем chunk'ам).
    Считаем динамически по БД `prepared_lectures`, поле `qa_questions`.
    """
    import sqlite3
    try:
        total = 0
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            try:
                c.execute(
                    "SELECT qa_questions FROM prepared_lectures WHERE topic=?",
                    (topic,),
                )
            except sqlite3.OperationalError:
                return 0
            for (raw,) in c.fetchall():
                total += len(_parse_qa_field(raw))
        return int(total)
    except (sqlite3.Error, OSError, ValueError):
        return 0


def get_qa_answers(topic: str, idx: int) -> list[str]:
    """
    Возвращает список ответов к вопросам для задания по теме/фрагменту
    из столбца qa_answers таблицы prepared_lectures.
    Возвращает пустой список, если данных нет. Поддерживает JSON-список или построчный текст.
    """
    import sqlite3
    import json as _json

    try:
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            cols = {row[1] for row in c.execute("PRAGMA table_info(prepared_lectures)")}
            if "qa_answers" not in cols:
                return []

            c.execute(
                "SELECT qa_answers FROM prepared_lectures WHERE topic=? AND chunk_idx=?",
                (topic, idx),
            )
            row = c.fetchone()
            if not row or not row[0]:
                return []

            raw = row[0]
            try:
                data = _json.loads(raw)
                return [str(x).strip() for x in data if str(x).strip()]
            except (json.JSONDecodeError, TypeError):
                lines = [ln.strip("- *\t ") for ln in str(raw).splitlines() if ln.strip()]
                return lines
    except (sqlite3.Error, OSError):
        return []


# ====== Новые разделы курса ======
BEGIN_CHEM_TOPICS = [
    "Строение атома",
    "Периодический закон",
    "Химическая связь",
    "Формула вещества",
    "Оксиды",
    "Основания и амфотерные гидроксиды",
    "Кислоты",
    "Соли",
]

ELEMENT_CHEM_TOPICS = [
    "ОВР",
    "Водород",
    "Галогены",
    "Кислород",
    "Сера",
    "Азот и фосфор",
    "Углерод и кремний",
    "Хром, марганец и алюминий",
    "Железо, медь, серебро, цинк",
]


def get_prepared_chunks_count(topic: str) -> int:
    """
    Возвращает количество подготовленных лекционных порций по теме из prepared_lectures.db.
    Берём max(chunk_idx) + 1. Если записей нет — 0.
    """
    import sqlite3

    with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
        c = conn.cursor()
        c.execute("SELECT MAX(chunk_idx) FROM prepared_lectures WHERE topic=?", (topic,))
        row = c.fetchone()
        if row and row[0] is not None:
            return int(row[0]) + 1
        return 0


def get_audio_from_db(topic: str, chunk_idx: int) -> tuple[bytes, str, int] | None:
    """
    Получает аудио из базы данных prepared_lectures.db.
    Возвращает (audio_blob, audio_format, duration_ms) или None если аудио нет.
    """
    import sqlite3

    with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT tts_audio, tts_audio_format, duration_ms 
            FROM prepared_lectures 
            WHERE topic=? AND chunk_idx=? AND tts_audio IS NOT NULL AND tts_audio != ''
            """,
            (topic, chunk_idx),
        )
        row = c.fetchone()
        if row:
            audio_blob, audio_format, duration_ms = row
            return audio_blob, (audio_format or 'ogg'), int(duration_ms or 0)
        return None


def _parse_qa_field(raw: str | bytes | None) -> list[str]:
    """
    Универсальный парсер поля с вопросами/ответами из БД.
    Поддерживает форматы:
      - JSON-массив строк
      - Обычный текст с разделителями по строкам
    Возвращает список непустых строк без нумерации типа "1) ", "- ".
    """
    if raw is None:
        return []
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="ignore")
        except (UnicodeDecodeError, AttributeError):
            raw = raw.decode("utf-8", errors="ignore")
    text = str(raw).strip()
    if not text:
        return []
    # Сначала пытаемся распарсить как JSON-массив
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            items = [str(x).strip() for x in obj]
        else:
            items = []
    except (json.JSONDecodeError, TypeError):
        # Фоллбэк: разбиваем по строкам
        lines = [ln.strip() for ln in text.splitlines()]
        items = [ln for ln in lines if ln]
    # Удаляем ведущую нумерацию/маркеры
    cleaned: list[str] = []
    for it in items:
        it2 = re.sub(r"^\s*(?:\d+[).:-]?\s+|[-••—]\s+)", "", it)
        cleaned.append(it2.strip())
    return [s for s in cleaned if s]


def get_qa_questions(topic: str, chunk_idx: int) -> list[str]:
    """
    Возвращает список вопросов для задания по теме/части из prepared_lectures.db.
    Если столбца нет или данных нет — пустой список.
    Ожидаемые столбцы: qa_questions (TEXT, JSON-массив или строки по одной в строке).
    """
    import sqlite3
    try:
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            try:
                c.execute(
                    "SELECT qa_questions FROM prepared_lectures WHERE topic=? AND chunk_idx=?",
                    (topic, int(chunk_idx)),
                )
            except sqlite3.OperationalError:
                # Нет такого столбца — возвращаем пусто
                return []
            row = c.fetchone()
            return _parse_qa_field(row[0]) if row else []
    except (sqlite3.Error, OSError):
        return []


def get_qa_answers(topic: str, chunk_idx: int) -> list[str]:
    """
    Возвращает список образцов ответов для задания по теме/части из prepared_lectures.db.
    Если столбца нет или данных нет — пустой список.
    Ожидаемые столбцы: qa_answers (TEXT, JSON-массив или строки по одной в строке).
    """
    import sqlite3
    try:
        with sqlite3.connect(PREPARED_LECTURES_DB) as conn:
            c = conn.cursor()
            try:
                c.execute(
                    "SELECT qa_answers FROM prepared_lectures WHERE topic=? AND chunk_idx=?",
                    (topic, int(chunk_idx)),
                )
            except sqlite3.OperationalError:
                return []
            row = c.fetchone()
            return _parse_qa_field(row[0]) if row else []
    except (sqlite3.Error, OSError):
        return []
