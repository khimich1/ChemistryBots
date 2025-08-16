import os
import sqlite3
from datetime import datetime
from typing import Dict, Tuple, List

# matplotlib без GUI
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Flowable, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from dotenv import load_dotenv
load_dotenv()

# Пути проекта
_THIS_DIR = os.path.dirname(__file__)
_BOT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, ".."))
_REPO_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", ".."))

FONTS_DIR = os.path.join(_BOT_ROOT, "..", "Fonts")
LOGO_PATH = os.path.join(FONTS_DIR, "Logo_Low.png")

DB_ANSWERS = os.getenv("DB_PATH") or os.path.join(_REPO_ROOT, "shared", "test_answers.db")
DB_TESTS = os.getenv("TESTS_DB_PATH") or os.path.join(_REPO_ROOT, "shared", "tests1.db")


def _register_fonts():
    regular_path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
    try:
        pdfmetrics.registerFont(TTFont("BodyFont", regular_path))
        pdfmetrics.registerFont(TTFont("HeaderFont", bold_path))
    except Exception:
        pass
    return "BodyFont", "HeaderFont"


BODY_FONT, HEADER_FONT = _register_fonts()


class SectionTitle(Flowable):
    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.height = 28

    def wrap(self, availWidth, availHeight):
        self.availWidth = availWidth
        return availWidth, self.height

    def draw(self):
        c = self.canv
        w, h = self.availWidth, self.height
        c.saveState()
        c.setFillColor(colors.HexColor("#fdebbd"))
        c.roundRect(0, 0, w, h, 10, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#2c3b62"))
        c.setFont(HEADER_FONT, 13)
        c.drawCentredString(w/2, 8, self.text)
        c.restoreState()


class TopTitle(Flowable):
    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.h = 40

    def wrap(self, availWidth, availHeight):
        self.w = availWidth
        return self.w, self.h

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(colors.HexColor("#f5c679"))
        c.roundRect(0, 0, self.w, self.h, 12, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#347b7b"))
        c.setFont(HEADER_FONT, 16)
        c.drawCentredString(self.w/2, 12, self.text)
        c.restoreState()


def _save_fig_tmp(fig, suffix=".png"):
    import tempfile
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    fig.savefig(f.name, bbox_inches="tight", dpi=170)
    plt.close(fig)
    return f.name


def _draw_donut(closed: int, total: int) -> str:
    total = max(total, 1)
    percent = 100.0 * closed / total if total else 0.0
    fig, ax = plt.subplots(figsize=(3.6, 3.6))
    ax.pie([closed, max(total - closed, 0)], colors=["#347b7b", "#e9eef2"], startangle=90, wedgeprops=dict(width=0.38))
    ax.text(0, 0, f"{percent:.0f}%", ha="center", va="center", fontsize=18, color="#2c3b62", fontweight="bold")
    ax.axis("equal")
    return _save_fig_tmp(fig)


def _load_test_stats(user_id: int) -> Dict[int, Tuple[int, int]]:
    stats: Dict[int, Tuple[int, int]] = {}
    try:
        with sqlite3.connect(DB_ANSWERS) as conn:
            c = conn.cursor()
            c.execute(
                """
                SELECT test_type, COUNT(*) AS total, COALESCE(SUM(is_correct), 0) AS correct
                FROM test_answers
                WHERE user_id=?
                GROUP BY test_type
                """,
                (user_id,),
            )
            for test_type, total, correct in c.fetchall():
                stats[int(test_type)] = (int(total or 0), int(correct or 0))
    except sqlite3.OperationalError:
        stats = {}
    return stats


def _detect_questions_per_test() -> int:
    try:
        with sqlite3.connect(DB_TESTS) as conn:
            c = conn.cursor()
            c.execute("SELECT MAX(cnt) FROM (SELECT type, COUNT(*) AS cnt FROM tests GROUP BY type)")
            row = c.fetchone()
            return int(row[0]) if row and row[0] is not None else 19
    except Exception:
        return 19


def _detect_num_test_types() -> int:
    try:
        with sqlite3.connect(DB_TESTS) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(DISTINCT type) FROM tests")
            row = c.fetchone()
            return int(row[0] or 28)
    except Exception:
        return 28


def make_report(user_id: int, fullname: str | None, filename: str = "report.pdf") -> str:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Info", fontName=BODY_FONT, fontSize=11, leading=14, textColor=colors.HexColor("#2c3b62")))
    styles.add(ParagraphStyle(name="NormalText", fontName=BODY_FONT, fontSize=11, leading=14, textColor=colors.HexColor("#2c3b62")))

    doc = SimpleDocTemplate(filename, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=28, bottomMargin=24)
    story: List = []

    story.append(TopTitle("Отчет по обучению"))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Имя: <b>{(fullname or '').strip() or '—'}</b>", styles["Info"]))
    story.append(Paragraph(f"Дата отчёта: <b>{datetime.now().strftime('%d.%m.%Y')}</b>", styles["Info"]))
    story.append(Spacer(1, 14))

    # Загрузка статистики
    test_stats = _load_test_stats(user_id)
    total_tests = _detect_num_test_types()
    questions_per_test = _detect_questions_per_test()
    tests_total_q = total_tests * questions_per_test
    tests_correct_sum = sum(int(v[1] or 0) for v in test_stats.values())
    donut_tests_path = _draw_donut(tests_correct_sum, tests_total_q)

    story.append(SectionTitle("Общий прогресс (тесты)"))
    cap_style = ParagraphStyle(name="Cap", fontName=HEADER_FONT, fontSize=11, leading=14, textColor=colors.HexColor("#2c3b62"), alignment=1)
    cell = [Image(donut_tests_path, width=200, height=200), Spacer(1, 4), Paragraph("Тесты", cap_style)]
    story.append(Table([[cell]], colWidths=[260]))
    story.append(Spacer(1, 12))

    story.append(SectionTitle("Прогресс по тестам"))
    # горизонтальные бары по тестам
    import numpy as np
    tests = list(range(1, total_tests + 1))
    correct_counts = [test_stats.get(t, (questions_per_test, 0))[1] for t in tests]
    labels = [f"{correct_counts[i]}/{questions_per_test}" for i in range(len(tests))]
    ylabels = [f"Тест {t}" for t in tests]
    y_pos = np.arange(len(ylabels))
    fig, ax = plt.subplots(figsize=(11.5, max(9.0, len(tests) * 0.5 + 2)))
    plt.subplots_adjust(left=0.22, right=0.98, top=0.96, bottom=0.12)
    bars = ax.barh(y_pos, correct_counts, color="#f5c679", edgecolor="#2c3b62", linewidth=1.0, height=0.6)
    ax.set_yticks(y_pos, labels=ylabels)
    ax.set_ylim(len(ylabels) - 0.5, -0.5)
    from matplotlib.ticker import MaxNLocator
    ax.set_xlim(0, questions_per_test)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xticks(list(range(0, questions_per_test + 1, 1)))
    ax.set_xlabel("Количество верных ответов", color="#2c3b62", fontweight="bold", fontsize=14)
    for bar, lab in zip(bars, labels):
        width = bar.get_width()
        ax.text(min(width + 0.3, questions_per_test - 0.3), bar.get_y() + bar.get_height()/2, lab, va="center", ha="left", fontsize=12, color="#000")
    img_tests = _save_fig_tmp(fig)
    story.append(Image(img_tests, width=500, height=580))
    story.append(Spacer(1, 12))

    doc.build(story)
    for p in (donut_tests_path, img_tests):
        try:
            os.remove(p)
        except Exception:
            pass
    return filename


