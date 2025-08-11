# bot/services/pdf_generator.py
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Dict, Tuple, List

# --- matplotlib без GUI ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Flowable,
    Table, TableStyle, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from bot.utils import ALL_TOPICS

# ───────── Палитра ─────────
CLR_ORANGE     = "#f5c679"   # светлооранжевый (бренд)
CLR_MALACHITE  = "#347b7b"   # малахитовый (бренд)
CLR_BLUE       = "#2c3b62"   # синий (бренд)
CLR_BG_FADE    = "#fdebbd"   # светлая подложка (fallback)
CLR_GREY_LIGHT = "#e9eef2"

# ──────── Пути проекта ────────
_THIS_DIR     = os.path.dirname(__file__)                    # bot/services
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", ".."))
FONTS_DIR     = os.path.join(_PROJECT_ROOT, "Fonts")
# важно: shared/test_answers.db лежит в корне проекта рядом с папкой bot
DB_ANSWERS    = os.path.join(_PROJECT_ROOT, "shared", "test_answers.db")
LOGO_PATH     = os.path.join(FONTS_DIR, "Logo_Low.png")      # путь к логотипу (если есть)

# ───────── Тестовый режим (заглушки) ─────────
USE_TEST_STUB = False  # ← включи True, если хочешь прогнать без БД/таблиц

# Заглушка по тестам: номер теста -> (всего, верно)
STUB_TEST_STATS: Dict[int, Tuple[int, int]] = {
    1: (19, 14),  2: (19, 0),   3: (19, 0),   4: (19, 0),
    5: (19, 5),   6: (19, 0),   7: (19, 0),   8: (19, 1),
    9: (19, 0),   10: (19, 1), 11: (19, 0),  12: (19, 0),
    13: (19, 0),  14: (19, 0), 15: (19, 0),  16: (19, 0),
    17: (19, 4),  18: (19, 0), 19: (19, 3),  20: (19, 0),
    21: (19, 0),  22: (19, 0), 23: (19, 0),  24: (19, 0),
    25: (19, 19), 26: (19, 1), 27: (19, 0),  28: (19, 0),
}
# Заглушка по «пройденным темам»
STUB_DONE_TOPICS: List[str] = ["Алканы", "Алкены", "Спирты"]

# ───────── Шрифты ─────────
def _register_fonts():
    """
    ReportLab: шрифты из папки Fonts.
    Matplotlib: тот же шрифт через font_manager + rcParams.
    """
    regular_path = os.path.join(FONTS_DIR, "LiberationSerif-Regular.ttf")
    bold_path    = os.path.join(FONTS_DIR, "LiberationSerif-Bold.ttf")

    # ReportLab
    if os.path.exists(regular_path) and os.path.exists(bold_path):
        pdfmetrics.registerFont(TTFont("BodyFont", regular_path))
        pdfmetrics.registerFont(TTFont("HeaderFont", bold_path))
        body, header = "BodyFont", "HeaderFont"
    else:
        # fallbacks (linux обычно)
        candidates = [
            ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        ]
        body, header = "Helvetica", "Helvetica-Bold"
        for reg, b in candidates:
            if os.path.exists(reg) and os.path.exists(b):
                pdfmetrics.registerFont(TTFont("BodyFont", reg))
                pdfmetrics.registerFont(TTFont("HeaderFont", b))
                body, header = "BodyFont", "HeaderFont"
                break

    # Matplotlib: тот же шрифт
    try:
        from matplotlib import font_manager as fm, rcParams
        if os.path.exists(regular_path):
            fm.fontManager.addfont(regular_path)
        if os.path.exists(bold_path):
            fm.fontManager.addfont(bold_path)
        rcParams["font.family"] = "Liberation Serif"
        rcParams["font.size"] = 10
        rcParams["axes.titlesize"] = 10
        rcParams["axes.labelsize"] = 10
    except Exception:
        pass

    return body, header

BODY_FONT, HEADER_FONT = _register_fonts()

# ───────── Вспомогалки ─────────
def _save_fig_tmp(fig, suffix=".png"):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    fig.savefig(f.name, bbox_inches="tight", dpi=170)
    plt.close(fig)
    return f.name

class SectionTitle(Flowable):
    """Заголовок секции по центру с полупрозрачной подложкой и паддингом."""
    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.height = 34

    def wrap(self, availWidth, availHeight):
        self.availWidth = availWidth
        return availWidth, self.height

    def draw(self):
        c = self.canv
        w, h = self.availWidth, self.height
        c.saveState()
        try:
            c.setFillColor(colors.HexColor(CLR_ORANGE))
            c.setFillAlpha(0.25)
            c.roundRect(0, 0, w, h, 10, stroke=0, fill=1)
            c.setFillAlpha(1)
        except Exception:
            c.setFillColor(colors.HexColor(CLR_BG_FADE))
            c.roundRect(0, 0, w, h, 10, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(CLR_BLUE))
        c.setFont(HEADER_FONT, 14)
        c.drawCentredString(w/2, 10, self.text)
        c.restoreState()

class TopTitle(Flowable):
    """Большой заголовок по центру с округлой подложкой и паддингом."""
    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.h = 46

    def wrap(self, availWidth, availHeight):
        self.w = availWidth
        return self.w, self.h

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(colors.HexColor(CLR_ORANGE))
        c.roundRect(0, 0, self.w, self.h, 16, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(CLR_MALACHITE))
        c.setFont(HEADER_FONT, 16)
        c.drawCentredString(self.w/2, 14, "Отчет по обучению")
        c.restoreState()


def _draw_topics_chart(done_topics: List[str]) -> str:
    """Горизонтальные бары по темам (0/1), цвета по циклу, равномерное распределение по высоте."""
    import numpy as np

    progress_data = [1 if t in done_topics else 0 for t in ALL_TOPICS]
    colors_cycle = [CLR_ORANGE, CLR_MALACHITE, CLR_BLUE]
    bar_colors = [colors_cycle[i % len(colors_cycle)] for i in range(len(ALL_TOPICS))]

    ylabels = ALL_TOPICS
    y_pos = np.arange(len(ylabels))  # равномерные позиции

    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    ax.barh(
        y_pos, progress_data,
        color=bar_colors,
        edgecolor=CLR_BLUE,
        linewidth=0.6,
        height=0.75
    )

    # равномерное распределение по всей высоте и порядок сверху вниз
    ax.set_yticks(y_pos, labels=ylabels)
    ax.set_ylim(len(ylabels) - 0.5, -0.5)

    ax.set_xlabel("1 — тема пройдена, 0 — нет", color=CLR_BLUE)
    ax.set_xlim(0, 1.05)
    ax.tick_params(colors=CLR_BLUE)
    ax.set_title("Статус по каждой теме", color=CLR_BLUE, fontsize=11)

    for spine in ax.spines.values():
        spine.set_edgecolor(CLR_BLUE)
    plt.tight_layout()
    return _save_fig_tmp(fig)


def _draw_tests_chart(test_stats: Dict[int, Tuple[int, int]]) -> str:
    """
    Горизонтальные бары по тестам 1..28.
    Цвета:
      - correct == 19 → малахит (CLR_MALACHITE) + надпись "GOOOOOOOL"
      - correct <= 8  → синий   (CLR_BLUE)
      - иначе         → оранж   (CLR_ORANGE)
    Ось X — целые 0..19. Первый тест сверху. Толстые полоски, крупные подписи.
    Равномерное распределение подписей по всей высоте графика.
    """
    import numpy as np

    tests = list(range(1, 29))
    total_questions = 19

    correct_counts, colors_bar, labels = [], [], []
    for t in tests:
        total, correct = test_stats.get(t, (total_questions, 0))
        correct_counts.append(correct)
        if correct >= total_questions:      # 19/19
            bar_color = CLR_MALACHITE
        elif correct <= 8:                  # 0..8
            bar_color = CLR_BLUE
        else:                               # 9..18
            bar_color = CLR_ORANGE
        colors_bar.append(bar_color)
        labels.append(f"{correct}/{total_questions}")

    ylabels = [f"Тест {t}" for t in tests]
    y_pos = np.arange(len(ylabels))  # равномерные позиции 0..27

    fig, ax = plt.subplots(figsize=(14, 14))
    bar_height = 1.0
    bars = ax.barh(
        y_pos, correct_counts,
        color=colors_bar,
        edgecolor=CLR_BLUE,
        linewidth=1.0,
        height=bar_height
    )

    # равномерно заполняем всю высоту и делаем «Тест 1» сверху
    ax.set_yticks(y_pos, labels=ylabels)
    ax.set_ylim(len(ylabels) - 0.5, -0.5)

    # шкала 0..19, целочисленная
    from matplotlib.ticker import MaxNLocator
    ax.set_xlim(0, total_questions)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xticks(list(range(0, total_questions + 1, 1)))
    ax.set_xlabel("Количество верных ответов", color=CLR_BLUE, fontweight="bold", fontsize=14)

    # без внутреннего заголовка
    ax.set_title("")

    # стиль осей
    ax.tick_params(colors=CLR_BLUE, labelsize=14)
    for spine in ax.spines.values():
        spine.set_edgecolor(CLR_BLUE)

    # подписи «Тест 1…»: малахит, жирные, крупные
    for lab in ax.get_yticklabels():
        lab.set_color(CLR_MALACHITE)
        lab.set_fontweight("bold")
        lab.set_fontsize(24)

    # подписи на барах и «GOOOOOOOL» для максимума
    for bar, lab, bar_color in zip(ax.patches, labels, colors_bar):
        width = bar.get_width()
        ax.text(
            width + 0.6 if width < total_questions - 1 else width - 1.0,
            bar.get_y() + bar.get_height() / 2,
            lab,
            va="center",
            ha="left" if width < total_questions - 1 else "right",
            fontsize=16,
            fontweight="bold",
            color=bar_color
        )
        if bar_color == CLR_MALACHITE:
            ax.text(
                max(width / 2, 0.5),
                bar.get_y() + bar.get_height() / 2,
                "GOOOOOOOL",
                va="center",
                ha="center",
                fontsize=18,
                fontweight="bold",
                color=CLR_ORANGE
            )

    # равномерная «воздушность» между строками
    plt.margins(y=0.05)
    plt.tight_layout()
    return _save_fig_tmp(fig)


def _draw_donut(closed: int, total: int) -> str:
    """Кольцевая диаграмма общего прогресса."""
    total = max(total, 1)
    percent = 100.0 * closed / total if total else 0.0
    fig, ax = plt.subplots(figsize=(3.8, 3.8))
    ax.pie(
        [closed, max(total - closed, 0)],
        colors=[CLR_MALACHITE, CLR_GREY_LIGHT],
        startangle=90,
        wedgeprops=dict(width=0.38)
    )
    ax.text(0, 0, f"{percent:.0f}%", ha="center", va="center",
            fontsize=22, color=CLR_BLUE, fontweight="bold")
    ax.axis("equal")
    return _save_fig_tmp(fig)


def _draw_logo(canvas, doc):
    """Рисует логотип в правом нижнем углу на каждой странице."""
    if not os.path.exists(LOGO_PATH):
        return
    canvas.saveState()
    try:
        # размеры страницы A4 и логотипа
        w, h = A4
        logo_w, logo_h = 70, 70  # в пунктах (1 pt ~ 1/72 дюйма)
        x = w - doc.rightMargin - logo_w
        y = doc.bottomMargin - 6  # чуть выше низа страницы
        canvas.drawImage(LOGO_PATH, x, y, width=logo_w, height=logo_h, mask='auto')
    finally:
        canvas.restoreState()


def _load_test_stats(user_id: int) -> Dict[int, Tuple[int, int]]:
    """
    Загружает статистику по тестам для пользователя из shared/test_answers.db:
      { test_type: (total_answers, correct_answers) }
    Если таблица отсутствует — вернём пустой словарь (PDF соберётся без графика тестов).
    """
    stats: Dict[int, Tuple[int, int]] = {}
    try:
        with sqlite3.connect(DB_ANSWERS) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT test_type,
                       COUNT(*)            AS total,
                       COALESCE(SUM(is_correct), 0) AS correct
                FROM test_answers
                WHERE user_id=?
                GROUP BY test_type
            """, (user_id,))
            for test_type, total, correct in c.fetchall():
                stats[int(test_type)] = (int(total or 0), int(correct or 0))
    except sqlite3.OperationalError:
        # например: no such table: test_answers — просто отдадим пустые данные
        stats = {}
    return stats


def make_report(user_id: int, fullname: str, records: List[dict], filename: str = "report.pdf") -> str:
    """
    Собирает PDF-отчёт:
      - Общий прогресс (два «бублика»: материалы и тесты)
      - Прогресс по темам (горизонтальные бары)
      - Прогресс по тестам (горизонтальные бары 1..28)
      - Комментарии GPT (из таблицы)
    Возвращает путь к созданному файлу PDF.
    """
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="Info",
        fontName=BODY_FONT, fontSize=11, leading=14,
        textColor=colors.HexColor(CLR_BLUE),
    ))
    styles.add(ParagraphStyle(
        name="NormalText",
        fontName=BODY_FONT, fontSize=11, leading=14,
        textColor=colors.HexColor(CLR_BLUE),
    ))
    styles.add(ParagraphStyle(
        name="Comment",
        fontName=BODY_FONT, fontSize=10, leading=14,
        textColor=colors.HexColor(CLR_MALACHITE),
    ))

    doc = SimpleDocTemplate(
        filename, pagesize=A4,
        leftMargin=36, rightMargin=36, topMargin=28, bottomMargin=24
    )
    story = []

    # ── ШАПКА
    story.append(TopTitle("Отчет по обучению"))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Имя: <b>{fullname or '—'}</b>", styles["Info"]))
    story.append(Paragraph(f"Дата отчёта: <b>{datetime.now().strftime('%d.%m.%Y')}</b>", styles["Info"]))
    story.append(Spacer(1, 14))

    # ── Данные
    if USE_TEST_STUB:
        done_topics = [t for t in ALL_TOPICS if t in STUB_DONE_TOPICS]
        test_stats = STUB_TEST_STATS
        if not records:
            records = [
                {
                    "Тема": "Алканы",
                    "Дата и время": "2025-08-08 14:30",
                    "Комментарий GPT": "Молодец! Хорошо разобрался с номенклатурой и изомерией. Обрати внимание на механизм радикального хлорирования."
                },
                {
                    "Тема": "Алкены",
                    "Дата и время": "2025-08-07 12:15",
                    "Комментарий GPT": "Понимаешь правило Марковникова. Попрактикуйся с примерами реакций присоединения и полимеризации."
                },
                {
                    "Тема": "Спирты",
                    "Дата и время": "2025-08-05 18:02",
                    "Комментарий GPT": "Классификация ок. Проверь различия в окислении первичных/вторичных спиртов."
                },
            ]
    else:
        done_topics = list({r.get("Тема", "") for r in records if r.get("Тема")})
        test_stats = _load_test_stats(user_id)

    # ── ДВА БУБЛИКА: Материалы + Тесты в ряд
    total_topics = len(ALL_TOPICS) or 1
    closed_topics = len([t for t in done_topics if t])
    donut_materials_path = _draw_donut(closed_topics, total_topics)

    tests_total_q = 28 * 19
    tests_correct_sum = sum(int(v[1] or 0) for v in test_stats.values())
    donut_tests_path = _draw_donut(tests_correct_sum, tests_total_q)

    story.append(SectionTitle("Общий прогресс"))
    cap_style = ParagraphStyle(
        name="Cap",
        fontName=HEADER_FONT, fontSize=11, leading=14,
        textColor=colors.HexColor(CLR_BLUE), alignment=1
    )
    cell1 = [Image(donut_materials_path, width=200, height=200), Spacer(1, 4), Paragraph("Материалы", cap_style)]
    cell2 = [Image(donut_tests_path,     width=200, height=200), Spacer(1, 4), Paragraph("Тесты", cap_style)]
    t = Table([[cell1, cell2]], colWidths=[260, 260])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # ── Диаграмма: прогресс по темам
    story.append(SectionTitle("Прогресс по темам"))
    topics_path = _draw_topics_chart(done_topics)
    story.append(Image(topics_path, width=420, height=260))
    story.append(Spacer(1, 10))

    # ── Диаграмма: прогресс по тестам (KeepTogether — заголовок + график вместе)
    tests_path = _draw_tests_chart(test_stats)
    story.append(KeepTogether([
        SectionTitle("Прогресс по тестам"),
        Image(tests_path, width=430, height=460),  # чутка выше под толстые полосы
    ]))
    story.append(Spacer(1, 12))

    # ── Комментарии GPT
    story.append(SectionTitle("Комментарии GPT"))
    story.append(Spacer(1, 6))
    for r in records:
        topic = r.get("Тема", "—")
        ts = r.get("Дата и время", "—")
        comment = (r.get("Комментарий GPT", "") or "").replace("\n", "<br/>")
        story.append(Paragraph(f"<b>Тема:</b> {topic}", styles["NormalText"]))
        story.append(Paragraph(f"<b>Дата:</b> {ts}", styles["NormalText"]))
        story.append(Paragraph(comment, styles["Comment"]))
        story.append(Spacer(1, 8))

    # Сборка PDF
    doc.build(story, onFirstPage=_draw_logo, onLaterPages=_draw_logo)

    # Чистим временные картинки
    for p in (donut_materials_path, donut_tests_path, topics_path, tests_path):
        try:
            os.remove(p)
        except Exception:
            pass

    return filename


