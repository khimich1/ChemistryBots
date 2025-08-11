import sqlite3

DB_FILE = "prepared_lectures.db"

with sqlite3.connect(DB_FILE) as conn:
    c = conn.cursor()
    # Создаём ТОЛЬКО новую таблицу, если её нет
    c.execute("""
        CREATE TABLE IF NOT EXISTS prepared_lectures (
            topic TEXT,
            chunk_idx INTEGER,
            orig_text TEXT,
            lecture TEXT,
            PRIMARY KEY (topic, chunk_idx)
        )
    """)
    conn.commit()
print("Таблица prepared_lectures успешно добавлена! Старые данные сохранены.")
