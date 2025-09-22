import os
import re
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
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
    pages: список словарей {title: str, question: str}
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
    max_width = (box_right - box_left) - 32

    def draw_text(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font: ImageFont.ImageFont, fill=(0, 0, 0)) -> int:
        # Разбиваем по словам с переносами по ширине
        words = (text or "").replace("\r", "").split()
        line = ""
        cur_y = y
        for w in words:
            test = (line + (" " if line else "") + w)
            w_width = draw.textlength(test, font=font)
            if w_width <= max_width:
                line = test
            else:
                if line:
                    _draw_with_sub_sup(draw, line, x, cur_y, font)
                    cur_y += line_height
                line = w
        if line:
            _draw_with_sub_sup(draw, line, x, cur_y, font)
            cur_y += line_height
        return cur_y

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

    def _new_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
        c = base.copy()
        return c, ImageDraw.Draw(c)

    for idx, page in enumerate(pages, start=1):
        canvas, d = _new_canvas()
        # Заголовок в оранжевом овале по центру
        title = page.get("title") or f"Задание №{idx}"
        title_color = (18, 121, 128)  # фирменный лазурный
        title_y = 54  # подняли ближе к верхней кромке овала
        title_w = d.textlength(title, font=font_bold)
        # Смещаем влево относительно центра овала (визуально как на примере)
        title_x = (width - title_w) / 2 - 120
        d.text((title_x, title_y), title, font=font_bold, fill=title_color)

        # Текст внутри оранжевой рамки/клетки
        y = margin_top
        # Текст задания
        text_block = page.get("question") or ""
        # Если есть варианты, добавим их ниже
        options = page.get("options") or ""
        if options:
            text_block = f"{text_block}\n\n{options}"
        # Уберём строку вида "Задание 9" / "Задание №9" из основного текста, если она в начале
        lines = [ln for ln in (text_block or "").split("\n")]
        if lines:
            first = lines[0].strip()
            if re.match(r"^Задание\s*№?\s*\d+\s*$", first, flags=re.IGNORECASE):
                lines = lines[1:]
        text_block = "\n".join(lines)
        # Поддержка плейсхолдеров картинок: [рисунок12345] (ЕГЭ) и [OGE12345] (ОГЭ)
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

        def _fetch_image_from_db(exam: str, qid: int, options_text: str) -> Image.Image | None:
            """Пытаемся достать изображение из БД по различным возможным схемам."""
            db_path = os.path.join(REPO_ROOT, "shared", "test_ege.db" if (exam or "").lower()=="ege" else "test_oge.db")
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.cursor()
                    # Вариант 1: отдельная таблица images/pictures
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
                            # id из options: вытаскиваем число
                            m = re.search(r"(\d+)", options_text or "")
                            code_num = int(m.group(1)) if m else None
                            # Пробуем по id
                            if id_col and code_num is not None:
                                cur.execute(f"SELECT {data_col} FROM {table} WHERE {id_col}=?", (code_num,))
                                row = cur.fetchone()
                                if row and row[0]:
                                    return Image.open(BytesIO(row[0]))
                            # Пробуем по имени/коду
                            if name_col and code_num is not None:
                                like = f"%{code_num:04d}%"
                                cur.execute(f"SELECT {data_col} FROM {table} WHERE {name_col} LIKE ? LIMIT 1", (like,))
                                row = cur.fetchone()
                                if row and row[0]:
                                    return Image.open(BytesIO(row[0]))
                        except sqlite3.OperationalError:
                            continue
                    # Вариант 2: картинка прямо в tests в столбце image/picture
                    cur.execute("PRAGMA table_info(tests)")
                    tcols = {r[1] for r in cur.fetchall()}
                    for c in ("image", "picture", "img", "figure", "pic"):
                        if c in tcols:
                            cur.execute(f"SELECT {c} FROM tests WHERE id=?", (qid,))
                            row = cur.fetchone()
                            if row and row[0]:
                                return Image.open(BytesIO(row[0]))
            except Exception:
                return None
            return None

        def _find_image_for(token: str, options_text: str, exam: str, qid: int) -> str | Image.Image | None:
            # 1) из токена [рисунок0001]
            code = token.strip("[] ")
            path = _find_image_by_code(code)
            if path:
                return path
            # 2) из options: может содержать id рисунка
            m = pic_id_re.search(options_text or "")
            if m:
                return _find_image_by_code(m.group(0))
            # 3) из БД (BLOB)
            img = _fetch_image_from_db(page.get("exam") or "ege", int(page.get("qid") or 0), options_text or "")
            if img:
                return img
            return None

        # Рисуем построчно с ограничением по нижней границе рамки, вставляя изображения по плейсхолдерам
        for para in (text_block or "").split("\n"):
            if not para.strip():
                y += line_height
                if y >= box_bottom:
                    break
                continue
            # Если параграф — это плейсхолдер изображения
            if img_token_re.fullmatch(para.strip()):
                found = _find_image_for(para.strip(), options, page.get("exam") or "ege", int(page.get("qid") or 0))
                # Если нашли как путь
                if isinstance(found, str) and os.path.exists(found):
                    try:
                        img = Image.open(found).convert("RGB")
                        # Масштабируем по ширине области, сохраняем пропорции
                        max_w = max_width
                        # Уменьшаем итоговый масштаб в 2 раза
                        scale = min(1.0, max_w / max(1, img.width)) * 0.5
                        new_w = int(img.width * scale)
                        new_h = int(img.height * scale)
                        # Перенос на новую страницу, если не помещается по высоте
                        if y + new_h > box_bottom - 10:
                            rendered.append(canvas)
                            canvas, d = _new_canvas()
                            d.text((title_x, title_y), title, font=font_bold, fill=title_color)
                            y = margin_top
                        img_resized = img.resize((new_w, new_h))
                        canvas.paste(img_resized, (margin_left, y))
                        y += new_h + int(line_height / 2)
                        continue
                    except Exception:
                        pass
                # Если пришло уже Image из БД
                if isinstance(found, Image.Image):
                    img = found
                    max_w = max_width
                    # Уменьшаем итоговый масштаб в 2 раза
                    scale = min(1.0, max_w / max(1, img.width)) * 0.5
                    new_w = int(img.width * scale)
                    new_h = int(img.height * scale)
                    if y + new_h > box_bottom - 10:
                        rendered.append(canvas)
                        canvas, d = _new_canvas()
                        d.text((title_x, title_y), title, font=font_bold, fill=title_color)
                        y = margin_top
                    img_resized = img.resize((new_w, new_h))
                    canvas.paste(img_resized, (margin_left, y))
                    y += new_h + int(line_height / 2)
                    continue
                # Если картинка не найдена — отрисуем текст как есть
            # вручную переносим параграф по ширине
            cur_y = y
            words = para.split()
            line = ""
            for w in words:
                test = (line + (" " if line else "") + w)
                if d.textlength(test, font=font_regular) <= max_width:
                    line = test
                else:
                    # Рисуем строку с поддержкой нижних/верхних индексов
                    _draw_with_sub_sup(d, line, margin_left, cur_y, font_regular)
                    cur_y += line_height
                    line = w
                if cur_y >= box_bottom:
                    break
            if cur_y < box_bottom and line:
                _draw_with_sub_sup(d, line, margin_left, cur_y, font_regular)
                cur_y += line_height
            y = cur_y
        rendered.append(canvas)

    if not output_path.lower().endswith(".pdf"):
        output_path = output_path + ".pdf"
    # Сохраняем все страницы в один PDF
    if rendered:
        first, rest = rendered[0], rendered[1:]
        first.save(output_path, save_all=True, append_images=rest)
    return output_path


