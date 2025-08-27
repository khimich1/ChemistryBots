import os
import sys

# Добавляем путь к скрипту
script_path = os.path.join("govr_bot", "scripts", "SQL", "новые тесты", "Новая папка")
sys.path.insert(0, script_path)

# Импортируем и запускаем основной скрипт
exec(open(os.path.join(script_path, "split_tasks.py"), encoding='utf-8').read())
