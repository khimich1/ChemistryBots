import os
import re
import sqlite3
from typing import Iterable, Set, Tuple, Optional, List
import time
import urllib.parse

import requests


# ====== Пути ======
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

SHARED_DIR = os.path.join(PROJECT_ROOT, "shared")
os.makedirs(SHARED_DIR, exist_ok=True)

# Куда положим собранный список веществ
SUBSTANCES_DB = os.path.join(SHARED_DIR, "substances.db")


# ====== Где взять prepared_lectures.db ======
def pick_prepared_lectures_db() -> str:
    """
    Выбираем БД с prepared_lectures:
    1) локальная govr_bot/bot/prepared_lectures.db, если есть
    2) переменная окружения PREPARED_LECTURES_DB, если указывает на файл
    3) shared/prepared_lectures.db
    """
    local_db = os.path.join(PROJECT_ROOT, "govr_bot", "bot", "prepared_lectures.db")
    if os.path.exists(local_db):
        return local_db

    env_db = os.getenv("PREPARED_LECTURES_DB")
    if env_db and os.path.exists(env_db):
        return env_db

    shared_db = os.path.join(SHARED_DIR, "prepared_lectures.db")
    return shared_db


PREPARED_LECTURES_DB = pick_prepared_lectures_db()


# ====== Регексы-кандидаты ======
# "… кислота"
ACID_RE = re.compile(r"\b([а-яё\-]+(?:\s+[а-яё\-]+){0,2})\s+кислота\b", re.IGNORECASE)
# "… спирт"
SPIRT_RE = re.compile(r"\b([а-яё\-]+)\s+спирт\b", re.IGNORECASE)
# Часто встречающиеся простые названия
WORD_RE = re.compile(
    r"\b(бензол|фенол|анилин|толуол|ацетон|глицерин|глюкоза|сахароза|ацетальдегид|бензальдегид|метан|этан|пропан|бутан|этилен|пропилен|ацетилен)\b",
    re.IGNORECASE,
)

# Формулы вида C6H6, CH3COOH и т.п. (минимум два блокa элемента)
FORMULA_RE = re.compile(r"\b(?:(?:C|H|O|N|S|P|Cl|Br|I)[a-z]?\d{0,3}){2,}\b")

# Сеть
REQUEST_TIMEOUT = 15
PAUSE_SEC = 0.2

# Мини-словарь соответствий RU -> EN для поиска по PubChem
RU2EN = {
    "этиловый спирт": "ethanol",
    "метиловый спирт": "methanol",
    "изопропиловый спирт": "isopropanol",
    "уксусная кислота": "acetic acid",
    "муравьиная кислота": "formic acid",
    "серная кислота": "sulfuric acid",
    "азотная кислота": "nitric acid",
    "фосфорная кислота": "phosphoric acid",
    "угольная кислота": "carbonic acid",
    "сернистая кислота": "sulfurous acid",
    "соляная кислота": "hydrochloric acid",
    "аммиак": "ammonia",
    "углекислый газ": "carbon dioxide",
    "угарный газ": "carbon monoxide",
    "сероводород": "hydrogen sulfide",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е").strip())


def extract_names_from_text(text: str) -> Set[str]:
    names: Set[str] = set()
    t = text or ""

    for m in ACID_RE.finditer(t):
        names.add(normalize_text(m.group(1) + " кислота"))

    for m in SPIRT_RE.finditer(t):
        base = normalize_text(m.group(1) + " спирт")
        # приведём распространённые варианты к каноническим
        if base.startswith("этилов"):
            names.add("этиловый спирт")
        elif base.startswith("метилов"):
            names.add("метиловый спирт")
        elif base.startswith("изопропил"):
            names.add("изопропиловый спирт")
        else:
            names.add(base)

    for m in WORD_RE.finditer(t):
        names.add(normalize_text(m.group(1)))

    return names


def extract_formulas_from_text(text: str) -> Set[str]:
    formulas: Set[str] = set()
    for m in FORMULA_RE.finditer(text or ""):
        f = m.group(0)
        if len(f) > 3:
            formulas.add(f)
    return formulas


def iter_prepared_texts(db_path: str) -> Iterable[str]:
    if not os.path.exists(db_path):
        print(f"[WARN] БД не найдена: {db_path}")
        return []

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        # Определим доступные столбцы
        cols = {row[1] for row in cur.execute("PRAGMA table_info(prepared_lectures)")}
        fields = [c for c in ("lecture", "qa_questions", "qa_answers") if c in cols]
        if not fields:
            print("[WARN] В prepared_lectures нет текстовых столбцов (lecture/qa_*)")
            return []
        q = f"SELECT {', '.join(fields)} FROM prepared_lectures"
        for row in cur.execute(q):
            for cell in row:
                if cell:
                    yield str(cell)


def ensure_schema(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS substances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name_ru TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                formula TEXT,
                iupac_name TEXT,
                trivial_names TEXT,
                first_source TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def upsert_substance(conn: sqlite3.Connection, name_ru: str, source: str) -> None:
    norm = normalize_text(name_ru)
    # Попытка увеличить счётчик, либо вставить новую запись
    updated = conn.execute(
        "UPDATE substances SET occurrence_count = occurrence_count + 1 WHERE normalized_name = ?",
        (norm,),
    )
    if updated.rowcount:
        return
    conn.execute(
        "INSERT OR IGNORE INTO substances(name_ru, normalized_name, first_source) VALUES (?, ?, ?)",
        (name_ru, norm, source),
    )


def pubchem_get_cid_by_name(name: str) -> Optional[int]:
    url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/cids/TXT".format(
        urllib.parse.quote(name, safe="")
    )
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        return None
    for line in r.text.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def pubchem_get_cid_by_formula(formula: str) -> Optional[int]:
    url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/formula/{}/cids/TXT".format(
        urllib.parse.quote(formula, safe="")
    )
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200 or not r.text.strip():
        return None
    ids = [ln.strip() for ln in r.text.splitlines() if ln.strip().isdigit()]
    return int(ids[0]) if len(ids) == 1 else None


def pubchem_get_props(cid: int) -> Tuple[Optional[str], Optional[str]]:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/MolecularFormula,Title/JSON"
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        return None, None
    try:
        data = r.json()
        p = data["PropertyTable"]["Properties"][0]
        return p.get("MolecularFormula"), p.get("Title")
    except Exception:
        return None, None


def pubchem_get_synonyms(cid: int) -> List[str]:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        return []
    try:
        data = r.json()
        syns = data["InformationList"]["Information"][0].get("Synonym", [])
        # Вернём первые 30, чтобы не раздувать поле
        return [str(s) for s in syns][:30]
    except Exception:
        return []


def update_details_if_missing(conn: sqlite3.Connection, norm_name: str, formula: Optional[str], iupac: Optional[str], trivial_candidates: List[str]) -> None:
    cur = conn.execute(
        "SELECT formula, iupac_name, trivial_names FROM substances WHERE normalized_name = ?",
        (norm_name,),
    )
    row = cur.fetchone()
    if not row:
        return
    cur_formula, cur_iupac, cur_trivial = row

    new_formula = cur_formula or formula or None
    new_iupac = cur_iupac or iupac or None
    # Собираем тривиальные: существующие + кандидаты (включая оригинальное RU имя)
    existing = set()
    if cur_trivial:
        existing |= {x.strip() for x in cur_trivial.split(";") if x.strip()}
    for s in trivial_candidates:
        s = str(s).strip()
        if s:
            existing.add(s)
    new_trivial = ";".join(sorted(existing)) if existing else None

    if new_formula != cur_formula or new_iupac != cur_iupac or new_trivial != cur_trivial:
        conn.execute(
            "UPDATE substances SET formula = ?, iupac_name = ?, trivial_names = ? WHERE normalized_name = ?",
            (new_formula, new_iupac, new_trivial, norm_name),
        )


def main() -> None:
    print(f"Использую prepared_lectures: {PREPARED_LECTURES_DB}")
    print(f"Формирую список веществ в: {SUBSTANCES_DB}")

    ensure_schema(SUBSTANCES_DB)

    names: Set[Tuple[str, str]] = set()
    formulas: Set[str] = set()
    for text in iter_prepared_texts(PREPARED_LECTURES_DB):
        for nm in extract_names_from_text(text):
            names.add((nm, "prepared_lectures"))
        for fm in extract_formulas_from_text(text):
            formulas.add(fm)

    print(f"Найдено кандидатов: имена={len(names)}, формулы={len(formulas)}")

    with sqlite3.connect(SUBSTANCES_DB) as conn:
        for name_ru, source in sorted(names):
            upsert_substance(conn, name_ru, source)
        conn.commit()

        # Попытаемся обогатить записи из PubChem
        for name_ru, _ in sorted(names):
            norm = normalize_text(name_ru)
            # Поиск CID: сначала по русскому, затем по словарю EN
            cid = pubchem_get_cid_by_name(name_ru)
            if not cid:
                cid = pubchem_get_cid_by_name(RU2EN.get(norm, RU2EN.get(name_ru.lower(), name_ru)))
            if not cid:
                continue
            formula, title = pubchem_get_props(cid)
            synonyms = pubchem_get_synonyms(cid)
            # Сформируем кандидатов тривиальных имен: оригинал RU + Title + часть синонимов
            trivial: List[str] = [name_ru]
            if title and title not in trivial:
                trivial.append(title)
            trivial.extend(synonyms[:20])

            update_details_if_missing(conn, norm, formula, title, trivial)
            time.sleep(PAUSE_SEC)

        # По формулам обновляем (только однозначный CID)
        for fm in sorted(formulas):
            cid = pubchem_get_cid_by_formula(fm)
            if not cid:
                continue
            formula, title = pubchem_get_props(cid)
            if not title:
                continue
            norm_title = normalize_text(title)
            # Если такой записи нет — заведем черновую
            cur = conn.execute("SELECT 1 FROM substances WHERE normalized_name = ?", (norm_title,)).fetchone()
            if not cur:
                conn.execute(
                    "INSERT OR IGNORE INTO substances(name_ru, normalized_name, first_source, formula, iupac_name) VALUES (?, ?, ?, ?, ?)",
                    (title, norm_title, "formula_detected", formula or fm, title),
                )
            # Попробуем добавить тривиальные синонимы
            synonyms = pubchem_get_synonyms(cid)
            update_details_if_missing(conn, norm_title, formula or fm, title, [title] + synonyms[:20])
            time.sleep(PAUSE_SEC)

    with sqlite3.connect(SUBSTANCES_DB) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM substances")
        total = cur.fetchone()[0]

    print(f"Готово. В таблице substances записей: {total}")
    print(f"База: {SUBSTANCES_DB}")


if __name__ == "__main__":
    main()


