import os, sqlite3

_THIS_DIR = os.path.dirname(__file__)            # bot/services
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
DB_FILE = os.path.join(_PROJECT_ROOT, "shared", "test_oge.db")

def _ensure_issue_columns():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS tests(
                    id INTEGER PRIMARY KEY,
                    type INTEGER,
                    question TEXT,
                    options TEXT,
                    correct_answer TEXT,
                    explanation TEXT,
                    hint TEXT,
                    detailed_explanation TEXT
                )
            """)
            cols = {row[1] for row in c.execute("PRAGMA table_info(tests)")}
            if "has_issue" not in cols:
                c.execute("ALTER TABLE tests ADD COLUMN has_issue INTEGER DEFAULT 0")
            if "issue_reason" not in cols:
                c.execute("ALTER TABLE tests ADD COLUMN issue_reason TEXT DEFAULT ''")
            if "issue_reported_at" not in cols:
                c.execute("ALTER TABLE tests ADD COLUMN issue_reported_at TEXT DEFAULT ''")
            conn.commit()
    except Exception:
        pass

_ensure_issue_columns()

def _detect_answer_column(conn: sqlite3.Connection) -> str:
    c = conn.cursor()
    c.execute("PRAGMA table_info(tests)")
    cols = {row[1] for row in c.fetchall()}
    if "correct_ans" in cols:    return "correct_ans"
    if "correct_answer" in cols: return "correct_answer"
    raise sqlite3.OperationalError("Нет колонки правильного ответа (correct_answer/correct_ans) в tests.")

def _ensure_tests_bug_table() -> None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tests_bug'")
            if c.fetchone(): return
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tests'")
            if not c.fetchone(): return
            c.execute("CREATE TABLE tests_bug AS SELECT * FROM tests WHERE 0")
            conn.commit()
    except Exception:
        pass

def copy_question_to_tests_bug(q_id: int) -> None:
    _ensure_tests_bug_table()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO tests_bug SELECT * FROM tests WHERE id=?", (int(q_id),))
            conn.commit()
    except Exception:
        pass

def get_all_tests_types():
    _ensure_issue_columns()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT type FROM tests ORDER BY type")
        all_types = [row[0] for row in c.fetchall() if row[0] not in (None, '')]
        # ОГЭ: только первые 19 тестов
        return all_types[:19]

def get_questions_by_type(test_type, limit: int = 30):
    _ensure_issue_columns()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        ans_col = _detect_answer_column(conn)
        safe_limit = int(limit) if isinstance(limit, int) and limit > 0 else 30
        sql = f"""
            SELECT id, question, options, {ans_col} AS correct_answer, explanation, hint, detailed_explanation
            FROM tests
            WHERE type=? AND COALESCE(has_issue,0)=0
            ORDER BY id
            LIMIT {safe_limit}
        """
        c.execute(sql, (test_type,))
        return [
            dict(
                id=row[0],
                question=row[1],
                options=row[2] or "",
                correct_answer=row[3] or "",
                explanation=row[4] or "",
                hint=row[5] or "",
                detailed_explanation=row[6] or "",
            )
            for row in c.fetchall()
        ]

def get_question_by_id(q_id):
    _ensure_issue_columns()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        ans_col = _detect_answer_column(conn)
        sql = (
            f"SELECT id, type, question, options, {ans_col} AS correct_answer, "
            f"explanation, hint, detailed_explanation, COALESCE(has_issue,0), COALESCE(issue_reason,'') "
            f"FROM tests WHERE id=?"
        )
        c.execute(sql, (q_id,))
        row = c.fetchone()
        if not row: return None
        return dict(
            id=row[0], type=row[1], question=row[2], options=row[3] or "",
            correct_answer=row[4] or "", explanation=row[5] or "",
            hint=row[6] or "", detailed_explanation=row[7] or "",
            has_issue=bool(row[8] or 0), issue_reason=row[9] or ""
        )

def mark_question_issue(q_id: int, reason: str | None = None) -> None:
    _ensure_issue_columns()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE tests
                SET has_issue=1,
                    issue_reason=COALESCE(?, issue_reason),
                    issue_reported_at=strftime('%Y-%m-%d %H:%M:%S','now')
                WHERE id=?
            """, (reason or None, q_id))
            conn.commit()
    except Exception:
        pass

def get_image_by_id(image_id: int) -> dict | None:
    """
    Получает изображение по его ID из таблицы images.
    Возвращает словарь с данными изображения или None, если не найдено.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, filename, mime_type, size_bytes, data, created_at FROM images WHERE id = ?",
                (image_id,)
            )
            row = c.fetchone()
            if row:
                return {
                    'id': row[0],
                    'filename': row[1],
                    'mime_type': row[2],
                    'size_bytes': row[3],
                    'data': row[4],  # BLOB данные
                    'created_at': row[5]
                }
            return None
    except Exception:
        return None

def get_question_with_image(q_id: int) -> dict | None:
    """
    Получает вопрос по ID с изображением, если оно есть.
    Возвращает словарь с данными вопроса и изображения или None, если не найдено.
    """
    _ensure_issue_columns()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            ans_col = _detect_answer_column(conn)
            sql = (
                f"SELECT id, type, question, options, {ans_col} AS correct_answer, "
                f"explanation, hint, detailed_explanation, COALESCE(has_issue,0), COALESCE(issue_reason,'') "
                f"FROM tests WHERE id=?"
            )
            c.execute(sql, (q_id,))
            row = c.fetchone()
            if not row:
                return None
            
            question_data = dict(
                id=row[0], type=row[1], question=row[2], options=row[3] or "",
                correct_answer=row[4] or "", explanation=row[5] or "",
                hint=row[6] or "", detailed_explanation=row[7] or "",
                has_issue=bool(row[8] or 0), issue_reason=row[9] or ""
            )
            
            # Если в options есть ID изображения, получаем изображение
            if question_data['options'] and question_data['options'].isdigit():
                image_id = int(question_data['options'])
                image_data = get_image_by_id(image_id)
                if image_data:
                    question_data['image'] = image_data
                    # Очищаем options, так как теперь это ID изображения
                    question_data['options'] = ""
            
            return question_data
    except Exception:
        return None

def get_questions_by_type_with_images(test_type, limit: int = 30) -> list[dict]:
    """
    Получает вопросы по типу теста с изображениями, если они есть.
    Возвращает список словарей с данными вопросов.
    """
    _ensure_issue_columns()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            ans_col = _detect_answer_column(conn)
            safe_limit = int(limit) if isinstance(limit, int) and limit > 0 else 30
            sql = f"""
                SELECT id, question, options, {ans_col} AS correct_answer, explanation, hint, detailed_explanation
                FROM tests
                WHERE type=? AND COALESCE(has_issue,0)=0
                ORDER BY id
                LIMIT {safe_limit}
            """
            c.execute(sql, (test_type,))
            questions = []
            
            for row in c.fetchall():
                question_data = dict(
                    id=row[0],
                    question=row[1],
                    options=row[2] or "",
                    correct_answer=row[3] or "",
                    explanation=row[4] or "",
                    hint=row[5] or "",
                    detailed_explanation=row[6] or "",
                )
                
                # Если в options есть ID изображения, получаем изображение
                if question_data['options'] and question_data['options'].isdigit():
                    image_id = int(question_data['options'])
                    image_data = get_image_by_id(image_id)
                    if image_data:
                        question_data['image'] = image_data
                        # Очищаем options, так как теперь это ID изображения
                        question_data['options'] = ""
                
                questions.append(question_data)
            
            return questions
    except Exception:
        return []
