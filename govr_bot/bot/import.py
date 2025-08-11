import sqlite3

DB_FILE = "tests1.db"

with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    c.execute("ALTER TABLE tests ADD COLUMN hint TEXT;")
    c.execute("ALTER TABLE tests ADD COLUMN detailed_explanation TEXT;")
    print("Готово! Новые поля добавлены.")
