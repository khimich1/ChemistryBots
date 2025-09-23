import os
import re
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import base64
import sqlite3

# Пути к ресурсам
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONTS_DIR = os.path.join(REPO_ROOT, "shared", "Fonts")
BASE_IMG = os.path.join(FONTS_DIR, "PDF_base.png")


def _load_fonts() -> Tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    regular_path = os.path.join(FONTS_DIR, "LiberationSerif-Regular.ttf")
    bold_path = os.path.join(FONTS_DIR, "LiberationSerif-Bold.ttf")
    try:
        # Ещё уменьшили основной шрифт внутри рамки
        f_regular = ImageFont.truetype(regular_path, 18)
    except Exception:
        f_regular = ImageFont.load_default()
    try:
        # Крупный заголовок, как в макете
        f_bold = ImageFont.truetype(bold_path, 64)
    except Exception:
        f_bold = ImageFont.load_default()
    return f_regular, f_bold


def _load_fallback_font(size: int) -> ImageFont.ImageFont:
    """Фолбэк-шрифт для индексов/маленьких цифр (имеет глифы ₂₃⁴ и т.п.)."""
    # Пытаемся загрузить DejaVuSans, обычно ставится вместе с Pillow
    for name in ("DejaVuSans.ttf", "DejaVuSerif.ttf", "FreeSerif.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    # В крайнем случае — системный дефолтный
    return ImageFont.load_default()


def render_questions_to_pdf(output_path: str, pages: List[dict]) -> str:
    """Рендерит список страниц в горизонтальный PDF.
    pages: список словарей {title: str, question: str, options?: str, exam?: str, qid?: int}
    Возвращает путь к pdf.
    """
    font_regular, font_bold = _load_fonts()
    base = Image.open(BASE_IMG).convert("RGB")
    width, height = base.size

    rendered: List[Image.Image] = []
    # Область белого листа в рамке (под текст): подгонялось под макет PDF_base.png
    box_left = 110
    box_top = 190  # немного ниже, чтобы текст гарантированно не упирался в рамку
    box_right = width - 110
    box_bottom = height - 95

    margin_left = box_left + 16
    margin_top = box_top + 18
    line_height = 28
    # Сдвигаем правую границу внутрь (автоперенос по "голубому краю")
    SAFE_RIGHT_PAD = 180
    max_width = (box_right - box_left) - 32 - SAFE_RIGHT_PAD

    state = {
        "canvas": None,
        "draw": None,
    }

    def _new_canvas():
        c = base.copy()
        state["canvas"] = c
        state["draw"] = ImageDraw.Draw(c)

    def _draw_with_sub_sup(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, base_font: ImageFont.ImageFont) -> None:
        """Рисует строку, заменяя последовательности вида H2SO4 на H₂SO₄ с фолбэк‑шрифтом.
        Только цифры после буквы считаются нижним индексом; цифры после ^ — верхним индексом.
        """
        # Фолбэк для индексов
        sub_font = _load_fallback_font(int(getattr(base_font, 'size', 18) * 0.85))
        sup_font = _load_fallback_font(int(getattr(base_font, 'size', 18) * 0.8))
        i = 0
        cx = x
        while i < len(text):
            ch = text[i]
            # Верхние индексы после '^'
            if ch == '^' and i + 1 < len(text) and text[i+1].isdigit():
                i += 1
                while i < len(text) and text[i].isdigit():
                    draw.text((cx, y - int(getattr(base_font, 'size', 18) * 0.35)), text[i], font=sup_font, fill=(0, 0, 0))
                    cx += draw.textlength(text[i], font=sup_font)
                    i += 1
                continue
            # Нижние индексы: цифры сразу после буквы/закрывающей скобки
            if ch.isdigit() and i > 0 and (text[i-1].isalpha() or text[i-1] in ")]"):
                draw.text((cx, y + int(getattr(base_font, 'size', 18) * 0.25)), ch, font=sub_font, fill=(0, 0, 0))
                cx += draw.textlength(ch, font=sub_font)
                i += 1
                # подряд идущие цифры
                while i < len(text) and text[i].isdigit():
                    draw.text((cx, y + int(getattr(base_font, 'size', 18) * 0.25)), text[i], font=sub_font, fill=(0, 0, 0))
                    cx += draw.textlength(text[i], font=sub_font)
                    i += 1
                continue
            # Обычный символ
            draw.text((cx, y), ch, font=base_font, fill=(0, 0, 0))
            cx += draw.textlength(ch, font=base_font)
            i += 1

    def _measure_with_sub_sup(draw: ImageDraw.ImageDraw, text: str, base_font: ImageFont.ImageFont) -> float:
        sub_font = _load_fallback_font(int(getattr(base_font, 'size', 18) * 0.85))
        sup_font = _load_fallback_font(int(getattr(base_font, 'size', 18) * 0.8))
        i = 0
        width_acc = 0.0
        while i < len(text):
            ch = text[i]
            if ch == '^' and i + 1 < len(text) and text[i+1].isdigit():
                i += 1
                while i < len(text) and text[i].isdigit():
                    width_acc += state["draw"].textlength(text[i], font=sup_font)
                    i += 1
                continue
            if ch.isdigit() and i > 0 and (text[i-1].isalpha() or text[i-1] in ")]"):
                width_acc += state["draw"].textlength(ch, font=sub_font)
                i += 1
                while i < len(text) and text[i].isdigit():
                    width_acc += state["draw"].textlength(text[i], font=sub_font)
                    i += 1
                continue
            width_acc += state["draw"].textlength(ch, font=base_font)
            i += 1
        return width_acc

    def _split_long_word(word: str, font: ImageFont.ImageFont) -> list[str]:
        parts: list[str] = []
        buf = ""
        for ch in word:
            if state["draw"].textlength(buf + ch, font=font) <= max_width:
                buf += ch
            else:
                if buf:
                    parts.append(buf)
                buf = ch
        if buf:
            parts.append(buf)
        return parts

    def draw_text(text: str, x: int, y: int, font: ImageFont.ImageFont) -> int:
        words = (text or "").replace("\r", "").split()
        line = ""
        cur_y = y
        for w in words:
            test = (line + (" " if line else "") + w)
            w_width = _measure_with_sub_sup(state["draw"], test, font)
            if w_width <= max_width:
                line = test
            else:
                if not line:
                    for chunk in _split_long_word(w, font):
                        _draw_with_sub_sup(state["draw"], chunk, x, cur_y, font)
                        cur_y += line_height
                        if cur_y + line_height > box_bottom:
                            rendered.append(state["canvas"])
                            _new_canvas()
                            state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                            cur_y = margin_top
                    line = ""
                else:
                    if cur_y + line_height > box_bottom:
                        rendered.append(state["canvas"])
                        _new_canvas()
                        state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                        cur_y = margin_top
                    _draw_with_sub_sup(state["draw"], line, x, cur_y, font)
                    cur_y += line_height
                    if cur_y + line_height > box_bottom:
                        rendered.append(state["canvas"])
                        _new_canvas()
                        state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                        cur_y = margin_top
                    line = w
            if cur_y + line_height > box_bottom:
                rendered.append(state["canvas"])
                _new_canvas()
                state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                cur_y = margin_top
        if line:
            if cur_y + line_height > box_bottom:
                rendered.append(state["canvas"])
                _new_canvas()
                state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                cur_y = margin_top
            _draw_with_sub_sup(state["draw"], line, x, cur_y, font)
            cur_y += line_height
        return cur_y

    def img_token_flow(question_text: str, options: str, exam: str, qid: int, start_y: int, task_type: int | None = None) -> tuple[int, bool]:
        img_token_re = re.compile(r"\[(?:рисунок\s*\d+|OGE\s*\d+)\]", re.IGNORECASE)
        pic_id_re = re.compile(r"(?:рисунок|OGE)\s*\d+", re.IGNORECASE)

        search_roots = [
            os.path.join(REPO_ROOT, "shared"),
            os.path.join(REPO_ROOT, "govr_bot"),
            os.path.join(REPO_ROOT, "prepod_bot"),
        ]
        _cache: dict[str, str] = {}

        def _find_image_by_code(code: str) -> str | None:
            code_norm = code.replace(" ", "").lower()
            if code_norm in _cache:
                return _cache.get(code_norm)
            for root in search_roots:
                if not os.path.isdir(root):
                    continue
                for dirpath, _, files in os.walk(root):
                    for f in files:
                        fl = f.lower()
                        if any(fl.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")) and code_norm in fl:
                            path = os.path.join(dirpath, f)
                            _cache[code_norm] = path
                            return path
            return None

        def _fetch_image_from_db(exam_local: str, qid_local: int, options_text: str) -> Image.Image | None:
            db_path = os.path.join(REPO_ROOT, "shared", "test_ege.db" if (exam_local or "").lower()=="ege" else "test_oge.db")
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.cursor()
                    for table in ("images", "pictures", "imgs", "figures"):
                        try:
                            cur.execute(f"PRAGMA table_info({table})")
                            cols = {r[1] for r in cur.fetchall()}
                            if not cols:
                                continue
                            id_col = "id" if "id" in cols else None
                            data_col = None
                            for c in ("data", "blob", "image", "img", "content", "bytes"):
                                if c in cols:
                                    data_col = c
                                    break
                            name_col = "filename" if "filename" in cols else ("code" if "code" in cols else None)
                            if not data_col:
                                continue
                            m = re.search(r"(\d+)", options_text or "")
                            code_num = int(m.group(1)) if m else None
                            if id_col and code_num is not None:
                                cur.execute(f"SELECT {data_col} FROM {table} WHERE {id_col}=?", (code_num,))
                                row = cur.fetchone()
                                if row and row[0]:
                                    return Image.open(BytesIO(row[0]))
                            if name_col and code_num is not None:
                                like = f"%{code_num:04d}%"
                                cur.execute(f"SELECT {data_col} FROM {table} WHERE {name_col} LIKE ? LIMIT 1", (like,))
                                row = cur.fetchone()
                                if row and row[0]:
                                    return Image.open(BytesIO(row[0]))
                        except sqlite3.OperationalError:
                            continue
                    cur.execute("PRAGMA table_info(tests)")
                    tcols = {r[1] for r in cur.fetchall()}
                    for c in ("image", "picture", "img", "figure", "pic"):
                        if c in tcols:
                            cur.execute(f"SELECT {c} FROM tests WHERE id=?", (qid_local,))
                            row = cur.fetchone()
                            if row and row[0]:
                                blob = row[0]
                                try:
                                    if isinstance(blob, (bytes, bytearray)):
                                        return Image.open(BytesIO(blob))
                                    if isinstance(blob, str):
                                        b64 = blob
                                        if "," in b64 and b64.strip().startswith("data:"):
                                            b64 = b64.split(",", 1)[1]
                                        return Image.open(BytesIO(base64.b64decode(b64)))
                                except Exception:
                                    return None
            except Exception:
                return None
            return None

        y_local = start_y
        image_used = False
        lines = [ln for ln in (question_text or "").split("\n")]
        for para in lines:
            if not para.strip():
                y_local += line_height
                if y_local >= box_bottom:
                    rendered.append(state["canvas"])
                    _new_canvas()
                    state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                    y_local = margin_top
                continue
            if img_token_re.fullmatch(para.strip()):
                found = None
                m = pic_id_re.search(options or "")
                if m:
                    found = _find_image_by_code(m.group(0))
                if not found:
                    found = _find_image_by_code(para.strip().strip("[] "))
                if not found:
                    found_img = _fetch_image_from_db(exam, qid, options or "")
                else:
                    found_img = None
                if isinstance(found, str) and os.path.exists(found):
                    try:
                        img = Image.open(found).convert("RGB")
                        max_w = max_width
                        scale = min(1.0, max_w / max(1, img.width)) * 0.5
                        new_w = int(img.width * scale)
                        new_h = int(img.height * scale)
                        if y_local + new_h > box_bottom - 10:
                            rendered.append(state["canvas"])
                            _new_canvas()
                            state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                            y_local = margin_top
                        img_resized = img.resize((new_w, new_h))
                        state["canvas"].paste(img_resized, (margin_left, y_local))
                        y_local += new_h + int(line_height / 2)
                        image_used = True
                        continue
                    except Exception:
                        pass
                if isinstance(found_img, Image.Image):
                    img = found_img
                    max_w = max_width
                    scale = min(1.0, max_w / max(1, img.width)) * 0.5
                    new_w = int(img.width * scale)
                    new_h = int(img.height * scale)
                    if y_local + new_h > box_bottom - 10:
                        rendered.append(state["canvas"])
                        _new_canvas()
                        state["draw"].text((title_x, title_y), title, font=font_bold, fill=title_color)
                        y_local = margin_top
                    img_resized = img.resize((new_w, new_h))
                    state["canvas"].paste(img_resized, (margin_left, y_local))
                    y_local += new_h + int(line_height / 2)
                    image_used = True
                    continue
            # не плейсхолдер — обычный текст
            test = para
            y_local = draw_text(test, margin_left, y_local, font_regular)
        return y_local, image_used

    for idx, page in enumerate(pages, start=1):
        _new_canvas()
        d = state["draw"]
        canvas = state["canvas"]
        # Заголовок в оранжевом овале по центру
        title = page.get("title") or f"Задание №{idx}"
        title_color = (18, 121, 128)
        title_y = 54
        title_w = d.textlength(title, font=font_bold)
        title_x = (width - title_w) / 2 - 120
        d.text((title_x, title_y), title, font=font_bold, fill=title_color)

        y = margin_top
        # Удаляем одиночную цифру в конце (ответ) из текста и options
        def _strip_trailing_number(s: str) -> str:
            s2 = (s or "").rstrip()
            s2 = re.sub(r"(?:\r?\n)\s*\d+\s*$", "", s2)
            return s2
        question_txt = _strip_trailing_number(page.get("question") or "")
        options = _strip_trailing_number(page.get("options") or "")
        # Рисуем вопрос и, если вставили картинку, не рисуем options
        y, used_image = img_token_flow(question_txt, options, page.get("exam") or "ege", int(page.get("qid") or 0), y, page.get("type"))
        # Доп. правило: для type==21 (ЕГЭ) в options может быть просто число — id изображения
        if not used_image and (page.get("exam") or "ege") == "ege" and int(page.get("type") or 0) == 21:
            m_id = re.fullmatch(r"\s*(\d+)\s*", options or "")
            if m_id:
                # имитируем плейсхолдер [рисунок0001]
                fake_token = f"[рисунок{int(m_id.group(1)):04d}]"
                y, used_image = img_token_flow("\n".join([fake_token]), options, "ege", int(page.get("qid") or 0), y, page.get("type"))
        if not used_image and options.strip():
            y = draw_text("\n" + options.strip(), margin_left, y, font_regular)
        rendered.append(state["canvas"])

    if not output_path.lower().endswith(".pdf"):
        output_path = output_path + ".pdf"
    if rendered:
        first, rest = rendered[0], rendered[1:]
        first.save(output_path, save_all=True, append_images=rest)
    return output_path


