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
import numpy as np

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Flowable,
    Table, TableStyle, KeepTogether, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ───────── Загрузка переменных окружения (.env) ─────────
from dotenv import load_dotenv
load_dotenv()

from bot.utils_pkg import ALL_TOPICS

# ───────── Палитра ─────────
CLR_ORANGE     = "#f5c679"   # светлооранжевый (бренд)
CLR_MALACHITE  = "#347b7b"   # малахитовый (бренд)
CLR_BLUE       = "#2c3b62"   # синий (бренд)
CLR_BG_FADE    = "#fdebbd"   # светлая подложка (fallback)
CLR_GREY_LIGHT = "#e9eef2"

# ──────── Пути проекта ────────
_THIS_DIR      = os.path.dirname(__file__)                    # bot/services
# root govr_bot (для ресурсов бота: Fonts и т.п.)
_BOT_ROOT      = os.path.normpath(os.path.join(_THIS_DIR, "..", ".."))
# корень всего репозитория ChemistryBots (для shared/*.db)
_REPO_ROOT     = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))

FONTS_DIR      = os.path.join(_BOT_ROOT, "Fonts")
LOGO_PATH      = os.path.join(FONTS_DIR, "Logo_Low.png")      # путь к логотипу (если есть)

# БД ответов (test_answers.db) хранится в общем каталоге shared
DB_ANSWERS     = os.path.join(_REPO_ROOT, "shared", "test_answers.db")

# БД вопросов тестов (tests1.db) — можно переопределить через .env
DB_TESTS       = os.getenv("TESTS_DB_PATH") or os.path.join(_REPO_ROOT, "shared", "tests1.db")

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

def _load_flashcards_stats(user_id: int) -> Tuple[int, int]:
    """
    Загружает статистику по карточкам для пользователя из shared/test_answers.db:
      (total_cards, correct_cards)
    Если таблица отсутствует — вернём (0, 0).
    """
    try:
        with sqlite3.connect(DB_ANSWERS) as conn:
            c = conn.cursor()
            # Общее количество карточек, которые видел пользователь
            c.execute("""
                SELECT COUNT(*) as total_cards
                FROM flashcards_seen
                WHERE user_id=?
            """, (user_id,))
            total_cards = c.fetchone()[0] or 0
            
            # Количество правильно решенных карточек
            c.execute("""
                SELECT COUNT(*) as correct_cards
                FROM flashcards_practice_log
                WHERE user_id=? AND is_correct=1
            """, (user_id,))
            correct_cards = c.fetchone()[0] or 0
            
            return int(total_cards), int(correct_cards)
    except sqlite3.OperationalError:
        # например: no such table: flashcards_seen — просто отдадим пустые данные
        return 0, 0

def _load_theory_stats_by_topic(user_id: int) -> Dict[str, Tuple[int, int]]:
    """
    Загружает статистику по теоретическим ответам по темам:
      { topic: (correct_answers, total_answers) }
    """
    stats: Dict[str, Tuple[int, int]] = {}
    try:
        with sqlite3.connect(DB_ANSWERS) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT topic,
                       SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct,
                       COUNT(*) AS total
                FROM theory_task_answers
                WHERE user_id=? AND is_correct IS NOT NULL
                GROUP BY topic
            """, (user_id,))
            for topic, correct, total in c.fetchall():
                stats[topic] = (int(correct or 0), int(total or 0))
    except sqlite3.OperationalError:
        pass
    return stats

def _create_topics_progress_bar(done_topics: List[str], theory_stats: Dict[str, Tuple[int, int]]) -> Flowable:
    """
    Создает простую процентную шкалу прогресса по всем темам.
    Минималистичный дизайн без графиков.
    """
    class TopicsProgressBar(Flowable):
        def __init__(self, done_topics, theory_stats):
            super().__init__()
            self.done_topics = done_topics
            self.theory_stats = theory_stats
            self.height = 60
            
        def wrap(self, availWidth, availHeight):
            self.availWidth = availWidth
            return availWidth, self.height
            
        def draw(self):
            c = self.canv
            w, h = self.availWidth, self.height
            
            # Вычисляем общий прогресс
            total_topics = len(ALL_TOPICS)
            completed_topics = len(set(self.done_topics))
            
            # Вычисляем средний процент по темам с детальной статистикой
            total_percent = 0
            topics_with_stats = 0
            
            for topic in ALL_TOPICS:
                if topic in self.theory_stats:
                    correct, total = self.theory_stats[topic]
                    if total > 0:
                        total_percent += (correct / total * 100)
                        topics_with_stats += 1
                elif topic in self.done_topics:
                    total_percent += 100
                    topics_with_stats += 1
            
            # Средний процент
            avg_percent = total_percent / total_topics if total_topics > 0 else 0
            
            c.saveState()
            
            # Фон шкалы
            c.setFillColor(colors.HexColor(CLR_GREY_LIGHT))
            c.roundRect(0, 20, w, 20, 10, stroke=0, fill=1)
            
            # Заполненная часть шкалы
            fill_width = (w * avg_percent) / 100
            if fill_width > 0:
                c.setFillColor(colors.HexColor(CLR_MALACHITE))
                c.roundRect(0, 20, fill_width, 20, 10, stroke=0, fill=1)
            
            # Текст с процентами
            c.setFillColor(colors.HexColor(CLR_BLUE))
            c.setFont(BODY_FONT, 12)
            c.drawCentredString(w/2, 45, f"Общий прогресс по темам: {avg_percent:.1f}%")
            
            # Дополнительная информация
            c.setFont(BODY_FONT, 10)
            c.drawCentredString(w/2, 5, f"Пройдено тем: {completed_topics}/{total_topics}")
            
            c.restoreState()
    
    return TopicsProgressBar(done_topics, theory_stats)

def _draw_flashcards_detailed_chart(user_id: int) -> str:
    """
    Создает детальную диаграмму прогресса по карточкам.
    Показывает статистику по категориям карточек.
    """
    try:
        with sqlite3.connect(DB_ANSWERS) as conn:
            c = conn.cursor()
            
            # Статистика по категориям карточек
            c.execute("""
                SELECT 
                    fs.category,
                    COUNT(DISTINCT fs.card_key) as seen_cards,
                    COUNT(DISTINCT CASE WHEN fpl.is_correct=1 THEN fpl.card_key END) as correct_cards,
                    COUNT(fpl.id) as total_attempts
                FROM flashcards_seen fs
                LEFT JOIN flashcards_practice_log fpl ON fs.user_id=fpl.user_id 
                    AND fs.category=fpl.category AND fs.card_key=fpl.card_key
                WHERE fs.user_id=?
                GROUP BY fs.category
                ORDER BY seen_cards DESC
            """, (user_id,))
            
            categories = []
            seen_counts = []
            correct_counts = []
            attempt_counts = []
            
            for row in c.fetchall():
                category, seen, correct, attempts = row
                # Изменяем названия категорий (проверяем оба регистра)
                if category.upper() == "INORG":
                    category = "НЕОРГАНИКА"
                elif category.upper() == "ORG":
                    category = "ОРГАНИКА"
                categories.append(category)
                seen_counts.append(seen or 0)
                correct_counts.append(correct or 0)
                attempt_counts.append(attempts or 0)
            
            if not categories:
                # Если нет данных, создаем пустой график
                fig, ax = plt.subplots(figsize=(10, 4))
                ax.text(0.5, 0.5, 'Нет данных по карточкам', 
                       ha='center', va='center', transform=ax.transAxes,
                       fontsize=14, color=CLR_BLUE)
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.axis('off')
                return _save_fig_tmp(fig)
            
            # Создаем график
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
            
            # График 1: Просмотренные vs правильно решенные карточки
            x = np.arange(len(categories))
            width = 0.35
            
            bars1 = ax1.bar(x - width/2, seen_counts, width, label='Просмотрено', 
                           color=CLR_ORANGE, alpha=0.8)
            bars2 = ax1.bar(x + width/2, correct_counts, width, label='Правильно решено', 
                           color=CLR_MALACHITE, alpha=0.8)
            
            ax1.set_xlabel('Категории карточек', fontsize=12, fontweight='bold', color=CLR_BLUE)
            ax1.set_ylabel('Количество карточек', fontsize=12, fontweight='bold', color=CLR_BLUE)
            ax1.set_title('Прогресс по карточкам по категориям', fontsize=14, fontweight='bold', color=CLR_BLUE)
            ax1.set_xticks(x)
            ax1.set_xticklabels(categories, rotation=45, ha='right')
            ax1.legend()
            ax1.grid(axis='y', alpha=0.3)
            
            # График 2: Количество попыток
            bars3 = ax2.bar(x, attempt_counts, color=CLR_BLUE, alpha=0.7)
            ax2.set_xlabel('Категории карточек', fontsize=12, fontweight='bold', color=CLR_BLUE)
            ax2.set_ylabel('Количество попыток', fontsize=12, fontweight='bold', color=CLR_BLUE)
            ax2.set_title('Количество попыток по категориям', fontsize=14, fontweight='bold', color=CLR_BLUE)
            ax2.set_xticks(x)
            ax2.set_xticklabels(categories, rotation=45, ha='right')
            ax2.grid(axis='y', alpha=0.3)
            
            # Добавляем значения на бары
            for bars in [bars1, bars2, bars3]:
                for bar in bars:
                    height = bar.get_height()
                    ax = bar.axes
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                           f'{int(height)}', ha='center', va='bottom',
                           fontsize=10, fontweight='bold')
            
            plt.tight_layout()
            return _save_fig_tmp(fig)
            
    except sqlite3.OperationalError:
        # Если таблицы нет, создаем пустой график
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, 'Нет данных по карточкам', 
               ha='center', va='center', transform=ax.transAxes,
               fontsize=14, color=CLR_BLUE)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        return _save_fig_tmp(fig)

def _extract_done_topics(records: List[dict]) -> List[str]:
    """Возвращает список уникальных КАНОНИЧЕСКИХ тем из записей Google Sheets.
    Нормализуем регистр/пробелы и учитываем только темы из `ALL_TOPICS`.
    Поддерживаем несколько возможных ключей в записях: 'Тема', 'Topic', 'topic'.
    """
    aliases = ("Тема", "Topic", "topic")
    def canonize(s: str) -> str:
        return (s or "").strip().lower().replace("ё", "е")

    canonical_by_lc = {canonize(t): t for t in ALL_TOPICS}
    result: set[str] = set()
    for r in records or []:
        raw = None
        for key in aliases:
            if key in r and r.get(key):
                raw = str(r.get(key))
                break
        if not raw:
            continue
        lc = canonize(raw)
        if lc in canonical_by_lc:
            result.add(canonical_by_lc[lc])
    return sorted(result)


def _get_done_topics_from_db(user_id: int) -> List[str]:
    """Возвращает список пройденных тем на основе данных из базы данных.
    Тема считается пройденной, если есть ответы в theory_task_answers.
    """
    def canonize(s: str) -> str:
        return (s or "").strip().lower().replace("ё", "е")

    canonical_by_lc = {canonize(t): t for t in ALL_TOPICS}
    result: set[str] = set()
    
    try:
        with sqlite3.connect(DB_ANSWERS) as conn:
            c = conn.cursor()
            # Получаем уникальные темы из theory_task_answers
            c.execute("""
                SELECT DISTINCT topic
                FROM theory_task_answers
                WHERE user_id=? AND topic IS NOT NULL AND TRIM(topic)!=''
            """, (user_id,))
            
            for (topic,) in c.fetchall():
                if topic:
                    lc = canonize(topic)
                    if lc in canonical_by_lc:
                        result.add(canonical_by_lc[lc])
    except sqlite3.OperationalError:
        pass
    
    return sorted(result)

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
    """Отрисовывает список тем в две колонки.
    Текст — жирный, малахитового цвета; у пройденных тем — галочка рядом.
    Возвращает путь к PNG для вставки в PDF.
    """
    import math

    topics: List[str] = list(ALL_TOPICS)
    total = len(topics)
    rows = math.ceil(total / 2)

    # Размер фигуры зависит от количества строк
    row_h = 1.0  # высота одной строки (увеличена под крупный шрифт)
    fig_w = 8.0
    fig_h = max(3.2, rows * row_h + 1.2)
    fig = plt.figure(figsize=(fig_w, fig_h))
    # Оставляем небольшие поля, чтобы текст не сплющивался при экспорте
    ax = fig.add_axes([0.04, 0.04, 0.92, 0.92])
    ax.axis("off")

    left_col = topics[:rows]
    right_col = topics[rows:]

    # Нормированные координаты для колонок и галочек
    y_step = 1.0 / (rows + 1)
    left_x_text = 0.08
    right_x_text = 0.58
    # Галочка слева от текста (небольшой фиксированный отступ)
    left_x_check = left_x_text - 0.03
    right_x_check = right_x_text - 0.03

    for i in range(rows):
        y = 1 - (i + 1) * y_step
        # Левая колонка
        if i < len(left_col):
            txt = left_col[i]
            ax.text(left_x_text, y, txt, color=CLR_MALACHITE, fontweight="bold",
                    fontsize=24, va="center", ha="left")
            if txt in done_topics:
                ax.text(
                    left_x_check, y, "\u2714", color=CLR_MALACHITE, fontsize=24,
                    va="center", ha="center", fontname="DejaVu Sans"
                )
        # Правая колонка
        if i < len(right_col):
            txt = right_col[i]
            ax.text(right_x_text, y, txt, color=CLR_MALACHITE, fontweight="bold",
                    fontsize=24, va="center", ha="left")
            if txt in done_topics:
                ax.text(
                    right_x_check, y, "\u2714", color=CLR_MALACHITE, fontsize=24,
                    va="center", ha="center", fontname="DejaVu Sans"
                )

    return _save_fig_tmp(fig)


def _draw_tests_chart(test_stats: Dict[int, Tuple[int, int]], *, questions_per_test: int, test_types: List[int] | None = None) -> str:
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

    tests = sorted(test_types) if test_types else sorted(test_stats.keys())
    if not tests:
        tests = [1]
    total_questions = max(1, int(questions_per_test))

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

    # Увеличенный, «воздушный» график с отступами между барами
    rows = len(ylabels)
    fig_w = 12.0
    fig_h = max(9.0, rows * 0.6 + 3.0)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    # Больше отступ слева и снизу (под легенду)
    plt.subplots_adjust(left=0.25, right=0.98, top=0.96, bottom=0.25)
    bar_height = 0.6  # меньше шага 1.0 → видимые промежутки между барами
    bars = ax.barh(
        y_pos, correct_counts,
        color=colors_bar,
        edgecolor=CLR_BLUE,
        linewidth=1.0,
        height=bar_height
    )

    # равномерно заполняем всю высоту и делаем «Тест 1» сверху
    # Подписи по оси Y выключаем — будем рисовать названия тестов вручную над барами
    ax.set_yticks(y_pos, labels=["" for _ in ylabels])
    ax.set_ylim(len(ylabels) - 0.5, -0.5)

    # шкала 0..N, целочисленная
    from matplotlib.ticker import MaxNLocator
    ax.set_xlim(0, total_questions)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xticks(list(range(0, total_questions + 1, 1)))
    ax.set_xlabel("Количество верных ответов", color=CLR_BLUE, fontweight="bold", fontsize=16)

    # без внутреннего заголовка
    ax.set_title("")

    # стиль осей
    ax.tick_params(colors=CLR_BLUE, labelsize=14)
    for spine in ax.spines.values():
        spine.set_edgecolor(CLR_BLUE)

    # Подписи «Тест N» слева от каждого бара (вне области данных)
    from matplotlib.transforms import blended_transform_factory
    trans = blended_transform_factory(ax.transAxes, ax.transData)
    for bar, t in zip(bars, tests):
        y_center = bar.get_y() + bar.get_height() / 2
        ax.text(
            -0.05,  # немножко левее оси
            y_center,
            f"Тест {t}",
            transform=trans,
            color=CLR_MALACHITE,
            fontweight="bold",
            fontsize=24,
            va="center",
            ha="right",
            clip_on=False,
        )

    # подписи на барах и «GOOOOOOOL» для максимума
    for bar, lab, bar_color in zip(ax.patches, labels, colors_bar):
        width = bar.get_width()
        x_text = min(width + 0.4, total_questions - 0.4)
        ax.text(
            x_text,
            bar.get_y() + bar.get_height() / 2,
            lab,
            va="center",
            ha="left",
            fontsize=20,
            fontweight="bold",
            color="#000000",
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

    # ── Легенда цветов снизу ──
    from matplotlib.patches import Patch
    legend_handles = [
        Patch(facecolor=CLR_BLUE, edgecolor=CLR_BLUE,
              label="Синий — меньше 9: старайся больше"),
        Patch(facecolor=CLR_ORANGE, edgecolor=CLR_ORANGE,
              label="Оранжевый — неплохо, но стоит поработать над ошибками"),
        Patch(facecolor=CLR_MALACHITE, edgecolor=CLR_MALACHITE,
              label="Малахитовый — ГОООООООО ОООООООООООООООООООООО ОООООООЛ"),
    ]
    from matplotlib.font_manager import FontProperties
    legend_fp = FontProperties(family="DejaVu Sans", size=16, weight="normal")
    ax.legend(
        handles=legend_handles,
        loc="upper left",
        bbox_to_anchor=(0.0, -0.18),
        frameon=False,
        ncol=1,
        prop=legend_fp,
        handlelength=1.6,
        handletextpad=0.6,
        borderaxespad=0.0,
    )
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
    # Имя берём из БД (user_profiles → test_answers), а переданный fullname используем как fallback
    resolved_fullname = _get_full_name_for_report(user_id, fallback_fullname=fullname)
    story.append(Paragraph(f"Имя: <b>{resolved_fullname or '—'}</b>", styles["Info"]))
    story.append(Paragraph(f"Дата отчёта: <b>{datetime.now().strftime('%d.%m.%Y')}</b>", styles["Info"]))
    story.append(Spacer(1, 14))

    # ── Данные
    # Определяем пройденные темы: сначала из records, потом из БД
    done_topics = _extract_done_topics(records)
    if not done_topics:  # Если records пустые, берем из БД
        done_topics = _get_done_topics_from_db(user_id)
    
    test_stats = _load_test_stats(user_id)
    theory_stats = _load_theory_stats_by_topic(user_id)
    flashcards_total, flashcards_correct = _load_flashcards_stats(user_id)

    # ── ДВА БУБЛИКА: Карточки + Тесты в ряд
    # Первый бублик: правильно пройденные карточки из общего количества
    donut_cards_path = _draw_donut(flashcards_correct, flashcards_total)

    # Второй бублик: тесты (как было)
    QUESTIONS_PER_TEST = _detect_questions_per_test()
    num_tests = _detect_num_test_types()
    tests_total_q = num_tests * QUESTIONS_PER_TEST
    tests_correct_sum = sum(int(v[1] or 0) for v in test_stats.values())
    donut_tests_path = _draw_donut(tests_correct_sum, tests_total_q)

    story.append(SectionTitle("Общий прогресс"))
    cap_style = ParagraphStyle(
        name="Cap",
        fontName=HEADER_FONT, fontSize=11, leading=14,
        textColor=colors.HexColor(CLR_BLUE), alignment=1
    )
    cell1 = [Image(donut_cards_path, width=200, height=200), Spacer(1, 4), Paragraph("Карточки", cap_style)]
    cell2 = [Image(donut_tests_path, width=200, height=200), Spacer(1, 4), Paragraph("Тесты", cap_style)]
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

    # ── Диаграмма: прогресс по темам (старый формат + процентная шкала)
    story.append(SectionTitle("Прогресс по темам"))
    topics_path = _draw_topics_chart(done_topics)
    story.append(Image(topics_path, width=420, height=260))
    story.append(Spacer(1, 10))
    
    # Добавляем простую процентную шкалу прогресса по темам
    story.append(_create_topics_progress_bar(done_topics, theory_stats))
    story.append(Spacer(1, 10))

    # ── Диаграмма: прогресс по тестам (KeepTogether — заголовок + график вместе)
    # На вертикальной шкале всегда показываем все типы тестов (1..num_tests),
    # даже если по части из них у пользователя ещё нет ответов
    all_test_types = list(range(1, num_tests + 1))
    tests_path = _draw_tests_chart(
        test_stats,
        questions_per_test=QUESTIONS_PER_TEST,
        test_types=all_test_types
    )
    story.append(KeepTogether([
        SectionTitle("Прогресс по тестам"),
        Image(tests_path, width=520, height=620),  # крупнее, почти на весь лист
    ]))
    story.append(Spacer(1, 12))

    # ── НОВАЯ СТРАНИЦА: Прогресс по карточкам
    story.append(PageBreak())  # Принудительный разрыв страницы
    story.append(SectionTitle("Прогресс по карточкам"))
    story.append(Spacer(1, 10))
    
    # Детальная диаграмма по карточкам
    flashcards_path = _draw_flashcards_detailed_chart(user_id)
    story.append(Image(flashcards_path, width=520, height=400))
    story.append(Spacer(1, 12))

    # Комментарии GPT удалены из отчёта

    # Сборка PDF
    doc.build(story, onFirstPage=_draw_logo, onLaterPages=_draw_logo)

    # Чистим временные картинки
    for p in (donut_cards_path, donut_tests_path, topics_path, tests_path, flashcards_path):
        try:
            os.remove(p)
        except Exception:
            pass

    return filename


def _get_full_name_for_report(user_id: int, *, fallback_fullname: str | None = None) -> str | None:
    """Достаём ФИО ученика из БД: сначала из user_profiles, потом из последних ответов.
    Если ничего нет — возвращаем fallback_fullname.
    """
    try:
        with sqlite3.connect(DB_ANSWERS) as conn:
            c = conn.cursor()
            # 1) user_profiles
            c.execute(
                "SELECT COALESCE(NULLIF(TRIM(full_name), ''), NULL) FROM user_profiles WHERE user_id=?",
                (user_id,)
            )
            row = c.fetchone()
            if row and row[0]:
                return row[0]
            # 2) test_answers (последний ответ с непустым full_name)
            c.execute(
                """
                SELECT full_name
                FROM test_answers
                WHERE user_id=? AND TRIM(COALESCE(full_name, ''))!=''
                ORDER BY answer_time DESC, id DESC
                LIMIT 1
                """,
                (user_id,)
            )
            row = c.fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return (fallback_fullname or "").strip() or None

def _detect_questions_per_test() -> int:
    """
    Максимальное количество вопросов на один тип теста по базе tests1.db.
    Если база/таблица недоступны — вернём 19 (стандарт ЕГЭ по химии).
    """
    try:
        with sqlite3.connect(DB_TESTS) as conn:
            c = conn.cursor()
            c.execute("SELECT MAX(cnt) FROM (SELECT type, COUNT(*) AS cnt FROM tests GROUP BY type)")
            row = c.fetchone()
            val = int(row[0]) if row and row[0] is not None else None
            return val or 19
    except Exception:
        return 19


def _detect_num_test_types() -> int:
    """
    Количество уникальных типов тестов по базе tests1.db.
    Если база/таблица недоступны — вернём 28.
    """
    try:
        with sqlite3.connect(DB_TESTS) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(DISTINCT type) FROM tests")
            row = c.fetchone()
            return int(row[0] or 28)
    except Exception:
        return 28

