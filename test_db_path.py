import os
from prepod_bot.config import DB_PATH, TESTS_DB_EGE, _SHARED_DIR

print("=== ПРОВЕРКА ПУТЕЙ К БАЗАМ ДАННЫХ ===")
print(f"SHARED_DIR: {_SHARED_DIR}")
print(f"DB_PATH: {DB_PATH}")
print(f"TESTS_DB_EGE: {TESTS_DB_EGE}")
print()

print("=== ПРОВЕРКА СУЩЕСТВОВАНИЯ ФАЙЛОВ ===")
print(f"DB_PATH существует: {os.path.exists(DB_PATH)}")
print(f"TESTS_DB_EGE существует: {os.path.exists(TESTS_DB_EGE)}")
print()

print("=== СОДЕРЖИМОЕ SHARED ===")
if os.path.exists(_SHARED_DIR):
    files = os.listdir(_SHARED_DIR)
    for f in sorted(files):
        if f.endswith('.db'):
            full_path = os.path.join(_SHARED_DIR, f)
            exists = os.path.exists(full_path)
            print(f"  {f}: {'✓' if exists else '✗'}")
else:
    print("  Папка shared не найдена!")
