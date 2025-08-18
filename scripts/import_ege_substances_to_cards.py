import os
import re
import csv
import time
import sqlite3
import urllib.parse
from typing import List, Dict, Optional, Tuple

import requests
import argparse


# ====== Пути ======
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

SOURCE_DB = os.path.join(PROJECT_ROOT, "shared", "ege_chemistry_substances.sqlite")

IMAGES_DIR = os.path.join(PROJECT_ROOT, "flashcards_bot", "images")
DATA_DIR = os.path.join(PROJECT_ROOT, "flashcards_bot", "data")
CARDS_CSV = os.path.join(DATA_DIR, "cards.csv")

os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


# ====== Сеть ======
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF = 1.5
PAUSE_SEC = 0.2


# ====== Утилиты ======
def normalize(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("\u00A0", " ")  # неразрывные пробелы
    text = re.sub(r"\s+", " ", text)
    return text


def split_trivial(raw: str) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[;,/\\|]+", raw)
    return [normalize(p) for p in parts if normalize(p)]


def read_existing_names(path: str) -> set:
    if not os.path.exists(path):
        return set()
    acc = set()
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            for n in (row.get("names") or "").split(";"):
                n = normalize(n).lower()
                if n:
                    acc.add(n)
    return acc


def detect_columns(conn: sqlite3.Connection, table: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Возвращает имена колонок: (formula_col, iupac_col, trivial_col)
    Колонки могут называться по‑разному на русском, берем эвристикой.
    """
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    low = [c.lower() for c in cols]

    def pick(*needles: str) -> Optional[str]:
        for i, c in enumerate(low):
            if any(nd in c for nd in needles):
                return cols[i]
        return None

    formula_col = pick("формул", "formula")
    trivial_col = pick("тривиал", "синоним")
    # IUPAC/номенклатурное название: сначала ищем по "номенк", затем iupac, затем общий "название"
    iupac_col = pick("номенк", "iupac", "название")
    # Если эвристика схватила ту же колонку, что и тривиальные, убираем
    if iupac_col == trivial_col:
        # попробуем найти альтернативное "название" без слова "тривиал"
        for i, c in enumerate(low):
            if "назван" in c and "тривиал" not in c:
                iupac_col = cols[i]
                break
        else:
            iupac_col = None
    return formula_col, iupac_col, trivial_col


# ====== PubChem API ======
def _http_get(url: str, params: Optional[dict] = None) -> Optional[requests.Response]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
            return r
        except Exception:
            if attempt == MAX_RETRIES:
                return None
            time.sleep(BACKOFF ** attempt)


def get_cid_by_formula(formula: str) -> Optional[int]:
    url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/formula/{}/cids/TXT".format(
        urllib.parse.quote(formula, safe="")
    )
    r = _http_get(url)
    if not r or r.status_code != 200 or not r.text.strip():
        return None
    ids = [ln.strip() for ln in r.text.splitlines() if ln.strip().isdigit()]
    # Раньше брали только однозначное совпадение. Теперь берём первый CID, чтобы не терять карточки.
    return int(ids[0]) if ids else None


def get_cid_by_name(name: str) -> Optional[int]:
    url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/cids/TXT".format(
        urllib.parse.quote(name, safe="")
    )
    r = _http_get(url)
    if not r or r.status_code != 200:
        return None
    for line in r.text.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def get_props_by_cid(cid: int) -> Tuple[Optional[str], Optional[str]]:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/MolecularFormula,Title/JSON"
    r = _http_get(url)
    if not r or r.status_code != 200:
        return None, None
    try:
        data = r.json()
        p = data["PropertyTable"]["Properties"][0]
        return p.get("MolecularFormula"), p.get("Title")
    except Exception:
        return None, None


def download_png_by_cid(cid: int, out_path: str) -> bool:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG"
    params = {"record_type": "2d", "image_size": "large"}
    r = _http_get(url, params=params)
    if not r or r.status_code != 200 or not r.content:
        return False
    with open(out_path, "wb") as f:
        f.write(r.content)
    return True


def sanitize_filename(name: str) -> str:
    name = normalize(name).lower()
    name = name.replace("ё", "е")
    name = re.sub(r"[^a-z0-9а-я_\-\.]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_") or "unnamed"


def main() -> None:
    parser = argparse.ArgumentParser(description="Import EGE substances DB → flashcards cards.csv")
    parser.add_argument("--limit", type=int, default=None, help="Макс. количество карточек для создания (для теста)")
    parser.add_argument("--verbose", action="store_true", help="Подробные логи по каждой строке")
    args = parser.parse_args()

    if not os.path.exists(SOURCE_DB):
        print("Не найдена БД:", SOURCE_DB)
        return

    existing_norm_names = read_existing_names(CARDS_CSV)
    rows_for_cards: List[Dict[str, str]] = []
    seen_files = set()

    added = 0
    with sqlite3.connect(SOURCE_DB) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print("Таблицы:", tables)
        for tbl in tables:
            f_col, i_col, t_col = detect_columns(conn, tbl)
            if not (f_col or i_col or t_col):
                continue
            # Составим SELECT с алиасами и кавычками вокруг идентификаторов
            f_expr = f'"{f_col}"' if f_col else 'NULL'
            i_expr = f'"{i_col}"' if i_col else 'NULL'
            t_expr = f'"{t_col}"' if t_col else 'NULL'
            sql = f'SELECT {f_expr} as formula, {i_expr} as iupac, {t_expr} as trivial FROM "{tbl}"'
            for formula, iupac, triv in conn.execute(sql):
                formula = normalize(formula)
                iupac = normalize(iupac)
                triv = normalize(triv)

                # Набор вариантов ответа
                variants: List[str] = []
                if iupac:
                    variants.append(iupac)
                variants.extend(split_trivial(triv))
                variants = [v for v in variants if v]
                if not variants:
                    continue

                # Пропустим полимерные формулы вида (...)n — PubChem часто возвращает много CIDs
                cid: Optional[int] = None
                if formula and "n" not in formula and "(" not in formula:
                    cid = get_cid_by_formula(formula)
                if not cid and iupac:
                    # Попробуем по IUPAC/англ названию (если в БД внезапно на англ.)
                    cid = get_cid_by_name(iupac)
                if not cid:
                    if args.verbose:
                        print(f"  [skip] {tbl}: формула='{formula}' iupac='{iupac}' — CID не найден")
                    continue

                pc_formula, title = get_props_by_cid(cid)
                out_name = variants[0]
                filename = f"{cid}_{sanitize_filename(out_name)}.png"
                out_path = os.path.join(IMAGES_DIR, filename)
                if filename in seen_files or os.path.exists(out_path):
                    # картинка уже есть — просто добавим строку
                    pass
                else:
                    if not download_png_by_cid(cid, out_path):
                        continue
                seen_files.add(filename)

                # Итоговая формула берём из PubChem при наличии
                final_formula = pc_formula or formula

                # Поле names: варианты через ; + добавим Title как ещё один вариант, если он не дублирует
                if title:
                    tnorm = normalize(title)
                    if tnorm and all(tnorm.lower() != normalize(v).lower() for v in variants):
                        variants.append(title)
                names_field = ";".join(variants)

                # Дубликаты по именам не добавляем
                if any(normalize(v).lower() in existing_norm_names for v in variants):
                    continue

                rows_for_cards.append({
                    "image": filename,
                    "formula": final_formula or "",
                    "names": names_field,
                })
                added += 1
                if args.verbose:
                    print(f"  [+] {tbl}: {out_name} | formula={final_formula or formula} | file={filename}")
                if args.limit and added >= args.limit:
                    break
                # чтобы не спамить API
                time.sleep(PAUSE_SEC)
            if args.limit and added >= args.limit:
                break
        # end for tables

    if not rows_for_cards and os.path.exists(CARDS_CSV):
        print("Новых карточек нет — возможно, все уже добавлены в cards.csv")
        print(CARDS_CSV)
        return

    write_header = not os.path.exists(CARDS_CSV)
    mode = "w" if write_header else "a"
    with open(CARDS_CSV, mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["image", "formula", "names"])
        if write_header:
            writer.writeheader()
        writer.writerows(rows_for_cards)

    print(f"Сохранено {len(rows_for_cards)} карточек → {CARDS_CSV}")
    print(f"Картинки → {IMAGES_DIR}")


if __name__ == "__main__":
    main()


