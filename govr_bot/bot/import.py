import sqlite3
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Путь к базе данных ЕГЭ
_THIS_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
DB_FILE = os.getenv("TESTS_DB_EGE") or os.path.join(_PROJECT_ROOT, "shared", "test_ege.db")

def add_columns_to_db():
    """Добавляет новые колонки в базу данных ЕГЭ"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("ALTER TABLE tests ADD COLUMN hint TEXT;")
            c.execute("ALTER TABLE tests ADD COLUMN detailed_explanation TEXT;")
            print("✅ Готово! Новые поля добавлены в базу данных ЕГЭ")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️  Колонки уже существуют в базе данных ЕГЭ")
        else:
            print(f"❌ Ошибка при работе с базой данных ЕГЭ: {e}")
    except Exception as e:
        print(f"❌ Неожиданная ошибка при работе с базой данных ЕГЭ: {e}")

# Добавляем колонки в базу ЕГЭ
print("🔄 Добавляем новые колонки в базу данных ЕГЭ...")
add_columns_to_db()
print("🎉 Миграция завершена!")
