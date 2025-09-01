from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
import difflib
import re
from typing import List, Optional, Dict, Any, Tuple

from aiogram import Router, types
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BufferedInputFile,
)
from aiogram.filters import Command

from bot.handlers.menu import main_kb
from bot.services.gpt_service import transcribe_audio, check_trivial_name_by_formula
from bot.services.answer_db import (
    flashcards_get_seen_set,
    flashcards_mark_seen,
    flashcards_reset_category,
    flashcards_add_error,
    flashcards_remove_error,
    flashcards_list_errors,
    flashcards_log_answer,
    flashcards_last_transcript,
    flashcards_count_wrong_voice_attempts,
)
from bot.utils_pkg_new.logger import log_error

router = Router()


# ====== Пути к БД ======
_THIS_DIR = os.path.dirname(__file__)  # govr_bot/bot/handlers
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
EGE_DB = os.path.join(_PROJECT_ROOT, "shared", "ege_chemistry_substances.sqlite")


# ====== Модель записи ======
@dataclass
class Substance:
    formula: str
    iupac: Optional[str]
    trivial: Optional[str]


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    return " ".join(str(text).replace("\u00A0", " ").split())


_SUBSCRIPT_DIGITS = str.maketrans({
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
})


def _format_formula(formula: Optional[str]) -> str:
    """Преобразует цифры индексов в подстрочные: C3H8 -> C₃H₈."""
    f = _normalize(formula)
    return f.translate(_SUBSCRIPT_DIGITS) if f else "—"


def _detect_columns(conn: sqlite3.Connection, table: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Эвристически находим имена колонок (formula, iupac, trivial)."""
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    low = [c.lower() for c in cols]

    def pick(*needles: str) -> Optional[str]:
        for i, c in enumerate(low):
            if any(nd in c for nd in needles):
                return cols[i]
        return None

    f_col = pick("формул", "formula")
    t_col = pick("тривиал", "синоним")
    i_col = pick("номенк", "iupac", "назван")
    if i_col == t_col:
        for i, c in enumerate(low):
            if "назван" in c and "тривиал" not in c:
                i_col = cols[i]
                break
        else:
            i_col = None
    return f_col, i_col, t_col


def _load_all_substances() -> List[Substance]:
    if not os.path.exists(EGE_DB):
        return []
    items: List[Substance] = []
    with sqlite3.connect(EGE_DB) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for tbl in tables:
            f_col, i_col, t_col = _detect_columns(conn, tbl)
            if not (f_col or i_col or t_col):
                continue
            f_expr = f'"{f_col}"' if f_col else 'NULL'
            i_expr = f'"{i_col}"' if i_col else 'NULL'
            t_expr = f'"{t_col}"' if t_col else 'NULL'
            sql = f'SELECT {f_expr} as formula, {i_expr} as iupac, {t_expr} as trivial FROM "{tbl}"'
            for fml, iup, trv in conn.execute(sql):
                fml = _normalize(fml)
                iup = _normalize(iup)
                trv = _normalize(trv)
                if not (fml or iup or trv):
                    continue
                items.append(Substance(formula=fml, iupac=iup or None, trivial=trv or None))
    return items


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def _load_from_named_table(table_name: str) -> List[Substance]:
    """Грузим записи строго из указанной таблицы (Неорганика/Органика)."""
    if not os.path.exists(EGE_DB):
        return []
    with sqlite3.connect(EGE_DB) as conn:
        if not _table_exists(conn, table_name):
            return []
        f_col, i_col, t_col = _detect_columns(conn, table_name)
        if not (f_col or i_col or t_col):
            return []
        f_expr = f'"{f_col}"' if f_col else 'NULL'
        i_expr = f'"{i_col}"' if i_col else 'NULL'
        t_expr = f'"{t_col}"' if t_col else 'NULL'
        sql = f'SELECT {f_expr} as formula, {i_expr} as iupac, {t_expr} as trivial FROM "{table_name}"'
        items: List[Substance] = []
        for fml, iup, trv in conn.execute(sql):
            fml = _normalize(fml)
            iup = _normalize(iup)
            trv = _normalize(trv)
            if not (fml or iup or trv):
                continue
            items.append(Substance(formula=fml, iupac=iup or None, trivial=trv or None))
        return items


def _is_organic(formula: str) -> bool:
    # Простая эвристика: наличие углерода
    return "C" in (formula or "")


# Кэшированные списки
# Сначала пробуем точные таблицы. Если их нет, используем эвристику по формуле.
INORG_ITEMS: List[Substance] = _load_from_named_table("Неорганика")
ORG_ITEMS: List[Substance] = _load_from_named_table("Органика")
if not INORG_ITEMS or not ORG_ITEMS:
    _all = _load_all_substances()
    if not INORG_ITEMS:
        INORG_ITEMS = [x for x in _all if not _is_organic(x.formula)]
    if not ORG_ITEMS:
        ORG_ITEMS = [x for x in _all if _is_organic(x.formula)]


# ====== Состояние пользователя ======
user_flashcards_state: Dict[int, Dict[str, Any]] = {}


# ====== Клавиатуры ======
cards_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📘 Заучивание")],
        [KeyboardButton(text="🧪 Практика")],
        [KeyboardButton(text="🛠 Работа над ошибками")],
        [KeyboardButton(text="🏠 В главное меню")],
    ],
    resize_keyboard=True,
)


def _make_reveal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Название", callback_data="fc_show_name"),
                InlineKeyboardButton(text="Следующее", callback_data="fc_next"),
            ],
            [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="fc_reset")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="fc_back")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="to_main_menu")],
        ]
    )


def _mode_select_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚗️ Неорганика"), KeyboardButton(text="🧬 Органика")],
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 В главное меню")],
        ],
        resize_keyboard=True,
    )


def _practice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Пропустить", callback_data="fc_practice_skip")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="fc_back")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="to_main_menu")],
        ]
    )


def _practice_next_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Далее", callback_data="fc_practice_next")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="to_main_menu")],
        ]
    )


def _format_names(sub: Substance) -> str:
    def clean_list(raw: Optional[str]) -> List[str]:
        if not raw:
            return []
        items = re.split(r"[;,/\\|]+", raw)
        cleaned: List[str] = []
        for it in items:
            s = _normalize(it)
            if not s or s in {"-", "—", "нет", "none", "n/a"}:
                continue
            if s not in cleaned:
                cleaned.append(s)
        return cleaned

    parts: List[str] = []
    iupac = _normalize(sub.iupac) if sub.iupac else ""
    if iupac and iupac not in {"-", "—", "нет", "none", "n/a"}:
        parts.append(f"<b>Номенклатурное название:</b> {iupac}")

    trivial_list = clean_list(sub.trivial)
    # Уберём дубликаты, совпадающие с IUPAC
    trivial_list = [t for t in trivial_list if t != iupac]
    if trivial_list:
        parts.append(f"<b>Тривиальные названия:</b> {'; '.join(trivial_list)}")

    if not parts:
        parts.append("Нет названий в базе")
    return "\n".join(parts)


# ====== ПРАКТИКА ======
def _extract_trivial_variants(sub: Substance) -> list[str]:
    txt = _normalize(sub.trivial)
    if not txt:
        return []
    items = re.split(r"[;,/\\|]+", txt)
    cleaned: list[str] = []
    for it in items:
        s = _normalize(it).lower()
        if s and s not in {"-", "—", "нет", "none", "n/a"} and s not in cleaned:
            cleaned.append(s)
    return cleaned


def _normalize_answer(text: str) -> str:
    # Базовая нормализация: регистр, трим, схлопывание пробелов, е/ё
    s = (text or "").lower().strip()
    s = s.replace("ё", "е")
    # Голос часто вставляет латинскую 'x' вместо кириллической 'х' в аббревиатуре "4-х"
    s = s.replace("x", "х")
    # Игнорируем префикс нормального ряда: n-/н- (н-пропиловый спирт ≈ пропиловый спирт)
    s = re.sub(r"\b[нn]\s*-\s*", "", s)
    s = " ".join(re.split(r"\s+", s))
    # Уберём финальную пунктуацию
    s = re.sub(r"[.,;:!?]+$", "", s)
    return s


def _escape_html(text: str) -> str:
    s = str(text or "")
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s


def _extract_iupac_variants(sub: Substance) -> list[str]:
    txt = _normalize(sub.iupac)
    if not txt:
        return []
    items = re.split(r"[;,/\\|]+", txt)
    cleaned: list[str] = []
    for it in items:
        s = _normalize(it).lower()
        if s and s not in {"-", "—", "нет", "none", "n/a"} and s not in cleaned:
            cleaned.append(s)
    return cleaned


def _matches_any(norm_user: str, variants: list[str]) -> bool:
    # Дополнительно допускаем различия только в разделителях: пробелы, дефисы, точки, слеши
    def _canon(s: str) -> str:
        s2 = _normalize_answer(s)
        s2 = re.sub(r"\s*\(.*?\)\s*", "", s2)  # убрать скобочные пометки
        s2 = re.sub(r"[\s\-._,/\\|]+", "", s2)
        return s2

    def _numeric_canon(s: str) -> str:
        t = _normalize_answer(s)
        # Приводим "4-х" / "4 х" / "4‑х" → просто "4"
        t = re.sub(r"(\d+)\s*[-–—]?\s*[xх]\b", r"\1", t)
        # Слова-числительные → цифры (основные варианты и приставки)
        maps: list[tuple[str, str]] = [
            (r"(один|одно|одна|моно)", "1"),
            (r"(двух|дву|два|ди)", "2"),
            (r"(тр[её]х|три)", "3"),
            (r"(четыр[её]х|четыре|тетра)", "4"),
            (r"(пяти|пента)", "5"),
            (r"(шести|гекса)", "6"),
            (r"(семи|гепта)", "7"),
            (r"(восьми|окта)", "8"),
            (r"(девяти|нона)", "9"),
            (r"(десяти|дека)", "10"),
        ]
        for pat, rep in maps:
            t = re.sub(pat, rep, t)
        # Убираем разделители
        t = re.sub(r"[\s\-._,/\\|]+", "", t)
        return t

    user_canon = _canon(norm_user)
    user_num = _numeric_canon(norm_user)
    for v in variants:
        nv = _normalize_answer(v)
        nv_core = re.sub(r"\s*\(.*?\)\s*", "", nv)
        if norm_user == nv or norm_user == nv_core or nv in norm_user or norm_user in nv or norm_user in nv_core:
            return True
        if user_canon and user_canon == _canon(nv):
            return True
        # Если хотя бы один из вариантов содержит цифру, сравниваем числовые каноны
        if user_num and (re.search(r"\d", nv) or re.search(r"\d", norm_user)):
            if user_num == _numeric_canon(nv):
                return True
    return False


async def start_practice_round(m: types.Message, category: str) -> None:
    user_id = m.from_user.id
    # Берём следующую карточку по тому же принципу, что и в заучивании, чтобы не повторять лишнее
    sub, title, idx = _pick_next_for_user(user_id, category)
    if not sub:
        await m.answer("База с веществами не найдена или пуста.", reply_markup=main_kb)
        return
    st = user_flashcards_state.setdefault(user_id, {})
    st["mode"] = "practice"
    st["last"] = sub
    st["last_category"] = category
    st["last_category_title"] = title
    st["awaiting_practice_answer"] = True
    total = len(INORG_ITEMS if category == "inorg" else ORG_ITEMS)
    text = (
        f"Практика — {title} (№ {idx + 1} из {total})\n"
        f"Назови тривиальное название по формуле:\n"
        f"<code>{_format_formula(sub.formula)}</code>\n"
        f"(можно голосом или текстом)"
    )
    sent = await m.answer(text, reply_markup=_practice_kb())
    st["practice_msg_id"] = sent.message_id


async def start_errors_round(m: types.Message, category: str) -> None:
    user_id = m.from_user.id
    errs = flashcards_list_errors(user_id, category)
    if not errs:
        st = user_flashcards_state.setdefault(user_id, {})
        st["awaiting_practice_answer"] = False
        st.pop("practice_msg_id", None)
        await m.answer("Ошибок пока нет — молодец!", reply_markup=_mode_select_kb())
        return
    # Берём первую ошибку
    card_key, formula, expected_variants = errs[0]
    st = user_flashcards_state.setdefault(user_id, {})
    st["mode"] = "errors"
    st["last_error_card_key"] = card_key
    st["last_error_expected"] = expected_variants
    st["last_error_formula"] = formula
    st["last_category"] = category
    st["awaiting_practice_answer"] = True
    sent = await m.answer(
        f"Работа над ошибками — назови тривиальное название:\n<code>{_format_formula(formula)}</code>",
        reply_markup=_practice_kb(),
    )
    st["practice_msg_id"] = sent.message_id


# Варианты для callback-обработчиков (не мутируем cb.message)
async def start_practice_round_cb(cb: CallbackQuery, category: str) -> None:
    user_id = cb.from_user.id
    sub, title, idx = _pick_next_for_user(user_id, category)
    if not sub:
        await cb.message.answer("База с веществами не найдена или пуста.", reply_markup=main_kb)
        return
    st = user_flashcards_state.setdefault(user_id, {})
    st["mode"] = "practice"
    st["last"] = sub
    st["last_category"] = category
    st["last_category_title"] = title
    st["awaiting_practice_answer"] = True
    total = len(INORG_ITEMS if category == "inorg" else ORG_ITEMS)
    text = (
        f"Практика — {title} (№ {idx + 1} из {total})\n"
        f"Назови тривиальное название по формуле:\n"
        f"<code>{_format_formula(sub.formula)}</code>\n"
        f"(можно голосом или текстом)"
    )
    sent = await cb.message.bot.send_message(chat_id=user_id, text=text, reply_markup=_practice_kb())
    st["practice_msg_id"] = sent.message_id


async def start_errors_round_cb(cb: CallbackQuery, category: str) -> None:
    user_id = cb.from_user.id
    errs = flashcards_list_errors(user_id, category)
    if not errs:
        st = user_flashcards_state.setdefault(user_id, {})
        st["awaiting_practice_answer"] = False
        st.pop("practice_msg_id", None)
        await cb.message.answer("Ошибок пока нет — молодец!", reply_markup=_mode_select_kb())
        return
    card_key, formula, expected_variants = errs[0]
    st = user_flashcards_state.setdefault(user_id, {})
    st["mode"] = "errors"
    st["last_error_card_key"] = card_key
    st["last_error_expected"] = expected_variants
    st["last_error_formula"] = formula
    st["last_category"] = category
    st["awaiting_practice_answer"] = True
    sent = await cb.message.bot.send_message(
        chat_id=user_id,
        text=f"Работа над ошибками — назови тривиальное название:\n<code>{_format_formula(formula)}</code>",
        reply_markup=_practice_kb(),
    )
    st["practice_msg_id"] = sent.message_id


# Приём ответа в режиме практики/ошибок: текст или голос
@router.message(lambda m: (user_flashcards_state.get(m.from_user.id) or {}).get("awaiting_practice_answer") is True)
async def practice_catch_answer(m: types.Message):
    st = user_flashcards_state.get(m.from_user.id) or {}
    category: str = st.get("last_category") or ""
    mode: str = st.get("mode") or "practice"
    
    # Проверяем, что пользователь действительно в режиме практики/ошибок
    if mode not in {"practice", "errors"}:
        # Если режим не установлен, сбрасываем флаг и игнорируем
        st["awaiting_practice_answer"] = False
        return
    
    # Проверяем, что есть активная карточка
    if mode == "practice" and not st.get("last"):
        st["awaiting_practice_answer"] = False
        return
    if mode == "errors" and not st.get("last_error_formula"):
        st["awaiting_practice_answer"] = False
        return
    
    expected_variants: list[str] = []
    # Обработка системных кнопок до начала проверки
    txt_raw = m.text or ""
    txt = txt_raw.strip()
    
    # Проверяем системные команды ПЕРЕД обработкой ответа
    if txt in {"Назад", "⬅️ Назад"}:
        st["awaiting_practice_answer"] = False
        # Сбрасываем состояние при возврате в меню
        user_id = m.from_user.id
        if user_id in user_flashcards_state:
            user_flashcards_state[user_id] = {}
        await m.answer("Выбери режим работы с карточками:", reply_markup=cards_kb)
        return
    if "в главное меню" in txt.lower():
        st["awaiting_practice_answer"] = False
        # Сбрасываем состояние при возврате в главное меню
        user_id = m.from_user.id
        if user_id in user_flashcards_state:
            user_flashcards_state[user_id] = {}
        await m.answer("Главное меню:", reply_markup=main_kb)
        return
    if txt in {"⚗️ Неорганика", "Неорганика"}:
        st["awaiting_practice_answer"] = False
        # Сбрасываем состояние при выборе раздела
        user_id = m.from_user.id
        user_flashcards_state[user_id] = {"mode": "practice"}
        await start_practice_round(m, category="inorg")
        return
    if txt in {"🧬 Органика", "Органика"}:
        st["awaiting_practice_answer"] = False
        # Сбрасываем состояние при выборе раздела
        user_id = m.from_user.id
        user_flashcards_state[user_id] = {"mode": "practice"}
        await start_practice_round(m, category="org")
        return
    # Показать индикатор обработки (скачивание/распознавание голоса может занимать время)
    loading_msg = await m.answer("⏳ Обрабатываю ответ... подожди немного.")
    expected_label: str = "Тривиальные названия"
    mixed_up_iupac: bool = False

    # Определим ожидаемые ответы
    if mode == "errors":
        # Восстановим полную карточку из ключа/формулы, чтобы иметь доступ и к IUPAC, и к тривиальным
        card_key = st.get("last_error_card_key")
        last_formula = st.get("last_error_formula")
        sub = _find_substance_by_key_or_formula(card_key, last_formula, category)
        if not sub:
            # Фоллбэк к тому, что было сохранено в ошибке
            raw = st.get("last_error_expected") or ""
            expected_variants = [s.strip().lower() for s in str(raw).split(";") if s.strip()]
            expected_label = "Тривиальные названия"  # предполагалось при сохранении
        else:
            trivial_variants = _extract_trivial_variants(sub)
            iupac_variants = _extract_iupac_variants(sub)
            if trivial_variants:
                expected_variants = trivial_variants
                expected_label = "Тривиальные названия"
            else:
                expected_variants = iupac_variants
                expected_label = "Номенклатурное название"
    else:
        current: Optional[Substance] = st.get("last")
        if not current:
            await m.answer("Сначала выбери раздел.")
            return
        trivial_variants = _extract_trivial_variants(current)
        iupac_variants = _extract_iupac_variants(current)
        if trivial_variants:
            expected_variants = trivial_variants
            expected_label = "Тривиальные названия"
        else:
            expected_variants = iupac_variants
            expected_label = "Номенклатурное название"

    # Извлекаем ответ пользователя: текст или голос
    user_answer = None
    if m.text and m.text.strip():
        user_answer = m.text.strip()
    elif getattr(m, "voice", None):
        from bot.services.plan import get_user_plan_code, limits_for, consume_daily
        plan = get_user_plan_code(m.from_user.id)
        limit = limits_for(plan)["theory_voice_per_day"]
        ok, _left = consume_daily(m.from_user.id, "theory_voice", limit)
        if not ok:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Тарифы и оплата", callback_data="to_tariffs")]
            ])
            await m.answer("Лимит голосовых ответов на сегодня исчерпан. Оформи подписку для безлимита.", reply_markup=kb)
            try:
                await loading_msg.delete()
            except (ValueError, TypeError) as e:
                log_error(e, f"Data error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
            except (AttributeError, KeyError) as e:
                log_error(e, f"Unexpected error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
            return
        try:
            file = await m.bot.get_file(m.voice.file_id)
            url = f"https://api.telegram.org/file/bot{m.bot.token}/{file.file_path}"
            import httpx, tempfile, os
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                fd, tmp_path = tempfile.mkstemp(suffix=".ogg")
                os.close(fd)
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
            user_answer = await transcribe_audio(tmp_path)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error transcribing audio for user {m.from_user.id}", user_id=m.from_user.id)
            user_answer = ""
        except (httpx.RequestError, OSError, IOError) as e:
            log_error(e, f"Unexpected error transcribing audio for user {m.from_user.id}", user_id=m.from_user.id)
            user_answer = ""
    else:
        # Удалим индикатор, если ответа нет
        try:
            await loading_msg.delete()
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
        return

    norm_user = _normalize_answer(user_answer)
    is_ok = _matches_any(norm_user, expected_variants)
    # В практике: если есть тривиальные, но пользователь сказал IUPAC — сообщим, что перепутал
    if True:
        # Проверяем «перепутал IUPAC» как в практике: если требуются тривиальные, а пользователь дал IUPAC
        if mode == "errors":
            card_key = st.get("last_error_card_key")
            last_formula = st.get("last_error_formula")
            sub = _find_substance_by_key_or_formula(card_key, last_formula, category)
        else:
            sub = st.get("last")
        if sub:
            trivial_variants = _extract_trivial_variants(sub)
            iupac_variants = _extract_iupac_variants(sub)
            # Перепутал: требуются тривиальные, но сказан IUPAC
            if trivial_variants and not _matches_any(norm_user, trivial_variants) and _matches_any(norm_user, iupac_variants):
                mixed_up_iupac = True

    # Сообщения и фиксация ошибок
    # Подготовим текст ответа с формулой и названиями
    if mode == "errors":
        formula = st.get("last_error_formula") or ""
        expected_display = st.get("last_error_expected") or ""
    else:
        cur: Optional[Substance] = st.get("last")
        formula = cur.formula if cur else ""
        expected_display = "; ".join(expected_variants)

    verdict = "✅ Верно!" if is_ok else ("❌ Неверно (перепутал: это номенклатурное название)" if mixed_up_iupac else "❌ Неверно")
    # Подсказка при многократной неудаче голосом
    hint = ""
    try:
        if not is_ok and mode == "errors":
            card_key = st.get("last_error_card_key") or ""
            if card_key:
                bad_voices = flashcards_count_wrong_voice_attempts(m.from_user.id, category, card_key)
                if bad_voices >= 1 and getattr(m, "voice", None):
                    hint = "\n\nИногда распознавание голосовых путает химические термины. Попробуйте ввести ответ текстом."
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error checking wrong voice attempts for user {m.from_user.id}", user_id=m.from_user.id)
    except (AttributeError, KeyError, sqlite3.Error) as e:
        log_error(e, f"Unexpected error checking wrong voice attempts for user {m.from_user.id}", user_id=m.from_user.id)

    reply_text = (
        f"{verdict}\n\n"
        f"Формула: <code>{_format_formula(formula)}</code>\n"
        f"Твой ответ: <code>{_escape_html(user_answer) or '—'}</code>\n"
        f"{expected_label}: {expected_display or '—'}"
        f"{hint}"
    )

    # Если это режим ошибок и верно — удалим из списка ошибок
    if is_ok and mode == "errors":
        card_key = st.get("last_error_card_key")
        if card_key:
            flashcards_remove_error(m.from_user.id, category, card_key)
    # Если практика и неверно — зафиксируем ошибку
    if not is_ok and mode == "practice":
        current: Optional[Substance] = st.get("last")
        if current:
            card_key = _card_key(current)
            expected = "; ".join(expected_variants)
            flashcards_add_error(m.from_user.id, category, card_key, _normalize(current.formula), expected)

    # Лог ответа (поможет посмотреть, как распозналось аудио)
    try:
        if mode == "errors":
            card_key = st.get("last_error_card_key") or ""
            formula = st.get("last_error_formula") or ""
        else:
            cur = st.get("last")
            card_key = _card_key(cur) if cur else ""
            formula = _normalize(cur.formula) if cur else ""
        flashcards_log_answer(
            user_id=m.from_user.id,
            category=category,
            card_key=card_key,
            formula=formula,
            answer_text=user_answer or "",
            source=("voice" if getattr(m, "voice", None) else "text"),
            is_correct=is_ok,
        )
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error logging flashcard answer for user {m.from_user.id}", user_id=m.from_user.id)
    except (AttributeError, KeyError, sqlite3.Error) as e:
        log_error(e, f"Unexpected error logging flashcard answer for user {m.from_user.id}", user_id=m.from_user.id)

    # Если локальная проверка не прошла, попробуем задать уточняющий вопрос LLM по формуле
    if not is_ok:
        # Определим формулу текущей карточки
        if mode == "errors":
            formula_for_llm = st.get("last_error_formula") or ""
        else:
            cur = st.get("last")
            formula_for_llm = _normalize(cur.formula) if cur else ""
        if formula_for_llm and user_answer:
            ok_llm, reason_llm = await check_trivial_name_by_formula(formula_for_llm, user_answer)
            if ok_llm:
                is_ok = True
                verdict = "✅ Верно!"
                # очищаем из ошибок, если надо
                if mode == "errors":
                    card_key = st.get("last_error_card_key")
                    if card_key:
                        flashcards_remove_error(m.from_user.id, category, card_key)
                # удаляем добавление в ошибки (если уже сделали) — не делаем, т.к. добавление ниже

    # Заменим предыдущее сообщение-вопрос на итог с кнопкой "Далее"
    msg_id = st.get("practice_msg_id")
    if msg_id:
        try:
            await m.bot.edit_message_text(
                chat_id=m.chat.id,
                message_id=msg_id,
                text=reply_text,
                reply_markup=_practice_next_kb(),
            )
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error editing message text for user {m.from_user.id}", user_id=m.from_user.id)
            await m.answer(reply_text, reply_markup=_practice_next_kb())
            st["practice_msg_id"] = None
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error editing message text for user {m.from_user.id}", user_id=m.from_user.id)
            await m.answer(reply_text, reply_markup=_practice_next_kb())
            st["practice_msg_id"] = None
    else:
        sent = await m.answer(reply_text, reply_markup=_practice_next_kb())
        st["practice_msg_id"] = sent.message_id
    # Удаляем индикатор обработки
    try:
        await loading_msg.delete()
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting loading message for user {m.from_user.id}", user_id=m.from_user.id)
    st["awaiting_practice_answer"] = False


@router.callback_query(lambda c: c.data == "fc_practice_next")
async def practice_next(cb: CallbackQuery):
    st = user_flashcards_state.get(cb.from_user.id) or {}
    category: str = st.get("last_category") or ""
    mode: str = st.get("mode") or "practice"
    # Удалим текущий итог
    msg_id = st.get("practice_msg_id")
    if msg_id:
        try:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=msg_id)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error deleting practice message for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error deleting practice message for user {cb.from_user.id}", user_id=cb.from_user.id)
    st["awaiting_practice_answer"] = True
    if mode == "errors":
        await start_errors_round_cb(cb, category)
    else:
        await start_practice_round_cb(cb, category)
    await cb.answer()
def _card_key(sub: Substance) -> str:
    f = _normalize(sub.formula)
    i = _normalize(sub.iupac)
    t = _normalize(sub.trivial)
    key = f or i or t or ""
    return key.lower()


def _pick_next_for_user(user_id: int, category: str) -> Tuple[Optional[Substance], str, int]:
    if category == "inorg":
        pool = INORG_ITEMS
        title = "Неорганика"
    else:
        pool = ORG_ITEMS
        title = "Органика"

    if not pool:
        return None, title, 0

    seen = flashcards_get_seen_set(user_id, category)
    for idx, sub in enumerate(pool):
        if _card_key(sub) not in seen:
            flashcards_mark_seen(user_id, category, _card_key(sub))
            return sub, title, idx

    # Все просмотрены — очищаем и начинаем сначала
    flashcards_reset_category(user_id, category)
    sub = pool[0]
    flashcards_mark_seen(user_id, category, _card_key(sub))
    return sub, title, 0


def _find_substance_by_key_or_formula(card_key: Optional[str], formula: Optional[str], category: str) -> Optional[Substance]:
    pool = INORG_ITEMS if category == "inorg" else ORG_ITEMS
    if card_key:
        for sub in pool:
            if _card_key(sub) == card_key:
                return sub
    if formula:
        norm = _normalize(formula)
        for sub in pool:
            if _normalize(sub.formula) == norm:
                return sub
    return None


async def _show_next_formula(message: types.Message, category: str) -> None:
    user_id = message.from_user.id
    if category == "inorg":
        pool = INORG_ITEMS
        title = "Неорганика"
    else:
        pool = ORG_ITEMS
        title = "Органика"

    if not pool:
        await message.answer(
            "База с веществами не найдена или пуста. Путь: " + EGE_DB,
            reply_markup=main_kb,
        )
        return

    state = user_flashcards_state.setdefault(user_id, {"idx_inorg": 0, "idx_org": 0, "last": None})
    state["last_category_title"] = title
    state["last_category"] = category

    current, title, idx = _pick_next_for_user(user_id, category)
    if not current:
        await message.answer(
            "База с веществами не найдена или пуста. Путь: " + EGE_DB,
            reply_markup=main_kb,
        )
        return
    state["last"] = current

    total = len(INORG_ITEMS if category == "inorg" else ORG_ITEMS)
    await message.answer(
        f"<b>{title}</b>\nФормула: <code>{_format_formula(current.formula)}</code>\n№ {idx + 1} из {total}",
        reply_markup=_make_reveal_kb(),
    )


# ====== Точки входа ======
@router.message(lambda m: m.text in ("🃏 Карточки для запоминания", "Карточки", "Карточки для запоминания"))
async def open_cards_menu(m: types.Message):
    # Сбрасываем состояние при входе в меню карточек
    user_id = m.from_user.id
    if user_id in user_flashcards_state:
        user_flashcards_state[user_id] = {}
    
    guide = (
        "🃏 Карточки для запоминания — как пользоваться:\n\n"
        "• 📘 Заучивание — листай формулы, раскрывай названия, закрепляй.\n"
        "• 🧪 Практика — по формуле назови тривиальное название (голосом или текстом).\n"
        "  Если голос распознаётся плохо — введи ответ текстом.\n"
        "• 🛠 Работа над ошибками — повтор карточек, где были ошибки.\n\n"
        "Кнопки:\n"
        "— ➡️ Пропустить / ➡️ Далее — перейти к следующей карточке\n"
        "— ⬅️ Назад — вернуться к выбору режима\n"
        "— 🏠 В главное меню — выйти в меню"
    )
    await m.answer(guide)
    await m.answer("Выбери режим работы с карточками:", reply_markup=cards_kb)
    # Подсказка: как посмотреть последнюю расшифровку
    # (для отладки голосовых ответов)
    # await m.answer("Подсказка: командой /last_voice можно посмотреть последнюю расшифровку ответа")


@router.message(Command("last_voice"))
async def show_last_voice(m: types.Message):
    try:
        row = flashcards_last_transcript(m.from_user.id)
        if not row:
            await m.answer("Пока нет записей голосовых/практики для этого пользователя.")
            return
        category, card_key, formula, answer_text = row
        title = "Неорганика" if category == "inorg" else "Органика" if category else "—"
        await m.answer(
            f"Последняя расшифровка:\n"
            f"Раздел: {title}\n"
            f"Формула: {formula or '—'}\n"
            f"Ключ: {card_key or '—'}\n"
            f"Текст: {answer_text or '—'}"
        )
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error getting last voice transcript for user {m.from_user.id}", user_id=m.from_user.id)
        await m.answer("Не удалось получить последнюю расшифровку.")
    except (AttributeError, KeyError, sqlite3.Error) as e:
        log_error(e, f"Unexpected error getting last voice transcript for user {m.from_user.id}", user_id=m.from_user.id)
        await m.answer("Не удалось получить последнюю расшифровку.")


@router.message(lambda m: m.text == "📘 Заучивание")
async def open_learn_menu(m: types.Message):
    # Сбрасываем состояние при выборе режима
    user_id = m.from_user.id
    user_flashcards_state[user_id] = {"mode": "learn"}
    await m.answer("Заучивание: выбери раздел", reply_markup=_mode_select_kb())


@router.message(lambda m: m.text == "🧪 Практика")
async def open_practice_menu(m: types.Message):
    # Сбрасываем состояние при выборе режима
    user_id = m.from_user.id
    user_flashcards_state[user_id] = {"mode": "practice"}
    await m.answer("Практика: выбери раздел", reply_markup=_mode_select_kb())


@router.message(lambda m: m.text == "🛠 Работа над ошибками")
async def open_errors_menu(m: types.Message):
    # Сбрасываем состояние при выборе режима
    user_id = m.from_user.id
    user_flashcards_state[user_id] = {"mode": "errors"}
    await m.answer("Работа над ошибками: выбери раздел", reply_markup=_mode_select_kb())


@router.message(lambda m: (m.text or "").strip() in {"Назад", "⬅️ Назад"})
async def nav_back(m: types.Message):
    # Возврат к выбору режима из уровня выбора раздела
    # Сбрасываем состояние при возврате в меню
    user_id = m.from_user.id
    if user_id in user_flashcards_state:
        user_flashcards_state[user_id] = {}
    await m.answer("Выбери режим работы с карточками:", reply_markup=cards_kb)


@router.message(lambda m: m.text == "⚗️ Неорганика")
async def cards_inorg(m: types.Message):
    # В зависимости от режима: заучивание/практика/ошибки
    mode = (user_flashcards_state.get(m.from_user.id) or {}).get("mode")
    if mode in {"practice", "errors"}:
        from bot.services.plan import flashcards_mode_allowed
        if not flashcards_mode_allowed(m.from_user.id, mode, "inorg"):
            await m.answer("Этот режим доступен на тарифах. Открой ‘💳 Тарифы и оплата’.")
            return
    if mode == "practice":
        await start_practice_round(m, category="inorg")
    elif mode == "errors":
        await start_errors_round(m, category="inorg")
    else:
        await _show_next_formula(m, category="inorg")


@router.message(lambda m: m.text == "🧬 Органика")
async def cards_org(m: types.Message):
    mode = (user_flashcards_state.get(m.from_user.id) or {}).get("mode")
    if mode in {"practice", "errors"}:
        from bot.services.plan import flashcards_mode_allowed
        if not flashcards_mode_allowed(m.from_user.id, mode, "org"):
            await m.answer("Этот режим доступен на тарифах. Открой ‘💳 Тарифы и оплата’.")
            return
    if mode == "practice":
        await start_practice_round(m, category="org")
    elif mode == "errors":
        await start_errors_round(m, category="org")
    else:
        await _show_next_formula(m, category="org")


@router.callback_query(lambda c: c.data == "fc_show_name")
async def reveal_name(cb: CallbackQuery):
    st = user_flashcards_state.get(cb.from_user.id) or {}
    # В режиме практика/ошибки показываем подсказку название не раскрываем
    if st.get("mode") in {"practice", "errors"}:
        await cb.answer("В этом режиме сначала назови тривиальное название")
        return
    current: Optional[Substance] = st.get("last")
    if not current:
        await cb.answer()
        await cb.message.answer("Сначала выбери раздел: Неорганика или Органика", reply_markup=cards_kb)
        return
    title = st.get("last_category_title") or "Карточки"
    text = (
        f"<b>{title}</b>\n"
        f"Формула: <code>{_format_formula(current.formula)}</code>\n"
        + _format_names(current)
    )
    try:
        await cb.message.edit_text(text, reply_markup=_make_reveal_kb())
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error editing message text in reveal_name for user {cb.from_user.id}", user_id=cb.from_user.id)
        # Если по каким-то причинам редактирование невозможно (например, старое сообщение), отправим новое
        await cb.message.answer(text, reply_markup=_make_reveal_kb())
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error editing message text in reveal_name for user {cb.from_user.id}", user_id=cb.from_user.id)
        # Если по каким-то причинам редактирование невозможно (например, старое сообщение), отправим новое
        await cb.message.answer(text, reply_markup=_make_reveal_kb())
    await cb.answer()


@router.callback_query(lambda c: c.data == "fc_next")
async def next_item(cb: CallbackQuery):
    user_id = cb.from_user.id
    st = user_flashcards_state.setdefault(user_id, {"idx_inorg": 0, "idx_org": 0})
    category: str = st.get("last_category") or ""
    if category not in ("inorg", "org"):
        await cb.answer()
        await cb.message.answer("Сначала выбери раздел: Неорганика или Органика", reply_markup=cards_kb)
        return
    
    idx_key = "idx_inorg" if category == "inorg" else "idx_org"
    # Если режим практика/ошибки — next показывает следующую карточку в том же режиме
    if st.get("mode") == "practice":
        await cb.answer()
        await start_practice_round_cb(cb, category)
        return
    if st.get("mode") == "errors":
        await cb.answer()
        await start_errors_round_cb(cb, category)
        return

    current, title, idx = _pick_next_for_user(user_id, category)
    st["last"] = current
    st["last_category_title"] = title

    total = len(INORG_ITEMS if category == "inorg" else ORG_ITEMS)
    text = f"<b>{title}</b>\nФормула: <code>{_format_formula(current.formula)}</code>\n№ {idx + 1} из {total}"
    try:
        await cb.message.edit_text(text, reply_markup=_make_reveal_kb())
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error editing message text in next_item for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer(text, reply_markup=_make_reveal_kb())
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error editing message text in next_item for user {cb.from_user.id}", user_id=cb.from_user.id)
        await cb.message.answer(text, reply_markup=_make_reveal_kb())
    await cb.answer()


@router.callback_query(lambda c: c.data == "fc_reset")
async def reset_cards(cb: CallbackQuery):
    st = user_flashcards_state.get(cb.from_user.id) or {}
    category: str = st.get("last_category") or ""
    if category not in ("inorg", "org"):
        await cb.answer()
        await cb.message.answer("Сначала выбери раздел: Неорганика или Органика", reply_markup=cards_kb)
        return
    flashcards_reset_category(cb.from_user.id, category)
    # Сброс работает для любого режима, но показываем первую карточку в текущем режиме
    if st.get("mode") == "practice":
        await start_practice_round_cb(cb, category)
    else:
        current, title, idx = _pick_next_for_user(cb.from_user.id, category)
        st["last"] = current
        st["last_category_title"] = title
        total = len(INORG_ITEMS if category == "inorg" else ORG_ITEMS)
        text = f"<b>{title}</b>\nФормула: <code>{_format_formula(current.formula)}</code>\n№ {idx + 1} из {total}"
        try:
            await cb.message.edit_text(text, reply_markup=_make_reveal_kb())
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error editing message text in reset_cards for user {cb.from_user.id}", user_id=cb.from_user.id)
            await cb.message.answer(text, reply_markup=_make_reveal_kb())
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error editing message text in reset_cards for user {cb.from_user.id}", user_id=cb.from_user.id)
            await cb.message.answer(text, reply_markup=_make_reveal_kb())
    await cb.answer("Начали сначала")


@router.callback_query(lambda c: c.data == "to_main_menu")
async def back_to_main_menu(cb: CallbackQuery):
    # Сбрасываем состояние при возврате в главное меню
    user_id = cb.from_user.id
    if user_id in user_flashcards_state:
        user_flashcards_state[user_id] = {}
    await cb.message.answer("Главное меню:", reply_markup=main_kb)
    await cb.answer()


@router.callback_query(lambda c: c.data == "fc_practice_skip")
async def practice_skip(cb: CallbackQuery):
    st = user_flashcards_state.get(cb.from_user.id) or {}
    category: str = st.get("last_category") or ""
    mode: str = st.get("mode") or "practice"
    # Удалим предыдущий вопрос/итог
    msg_id = st.get("practice_msg_id")
    if msg_id:
        try:
            await cb.message.bot.delete_message(chat_id=cb.message.chat.id, message_id=msg_id)
        except (ValueError, TypeError) as e:
            log_error(e, f"Data error deleting practice message in practice_skip for user {cb.from_user.id}", user_id=cb.from_user.id)
        except (AttributeError, KeyError) as e:
            log_error(e, f"Unexpected error deleting practice message in practice_skip for user {cb.from_user.id}", user_id=cb.from_user.id)
    if mode == "errors":
        await start_errors_round_cb(cb, category)
    else:
        await start_practice_round_cb(cb, category)
    await cb.answer()


@router.callback_query(lambda c: c.data == "fc_back")
async def inline_back(cb: CallbackQuery):
    st = user_flashcards_state.get(cb.from_user.id) or {}
    # Больше не ждём ответ по практике
    st["awaiting_practice_answer"] = False
    # Удалим текущее сообщение с инлайн-кнопками (если возможно)
    try:
        await cb.message.delete()
    except (ValueError, TypeError) as e:
        log_error(e, f"Data error deleting message in inline_back for user {cb.from_user.id}", user_id=cb.from_user.id)
    except (AttributeError, KeyError) as e:
        log_error(e, f"Unexpected error deleting message in inline_back for user {cb.from_user.id}", user_id=cb.from_user.id)
    # Вернёмся на уровень выбора раздела внутри текущего режима
    # Сохраняем только режим, остальное сбрасываем
    mode = st.get("mode")
    user_id = cb.from_user.id
    user_flashcards_state[user_id] = {"mode": mode} if mode else {}
    await cb.message.answer("Выбери раздел", reply_markup=_mode_select_kb())
    await cb.answer()

