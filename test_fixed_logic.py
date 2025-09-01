#!/usr/bin/env python3
"""
Тестовый скрипт для проверки исправленной логики подсчета оставшихся вопросов
"""

def test_fixed_remaining_questions_logic():
    """Тестируем исправленную логику подсчета: неотвеченные + ошибочные"""
    print("🧪 Тестируем исправленную логику подсчета оставшихся вопросов...")
    
    # Имитируем состояние пользователя
    total_questions = 5  # Всего вопросов в куске
    
    # Тест 1: Начальное состояние - все вопросы неотвеченные
    print("\n--- Тест 1: Начальное состояние ---")
    answered_set = set()  # Пока не отвечали ни на один вопрос
    wrong_set = set()     # Пока нет ошибочных
    
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    
    print(f"Всего вопросов: {total_questions}")
    print(f"Отвеченные: {len(answered_set)}")
    print(f"Неотвеченные: {unanswered}")
    print(f"Ошибочные: {len(wrong_set)}")
    print(f"Оставшихся всего: {remaining_total}")
    print(f"Кнопка: {'🔁 Другой вопрос (5)' if remaining_total > 0 else '🔁 Другой вопрос'}")
    
    # Тест 2: Ответили на 2 вопроса, 1 из них неправильно
    print("\n--- Тест 2: Ответили на 2 вопроса, 1 неправильно ---")
    answered_set = {0, 1}  # Ответили на вопросы 0 и 1
    wrong_set = {0}        # Вопрос 0 был неправильным
    
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    
    print(f"Всего вопросов: {total_questions}")
    print(f"Отвеченные: {len(answered_set)}")
    print(f"Неотвеченные: {unanswered}")
    print(f"Ошибочные: {len(wrong_set)}")
    print(f"Оставшихся всего: {remaining_total}")
    print(f"Кнопка: {'🔁 Другой вопрос (4)' if remaining_total > 0 else '🔁 Другой вопрос'}")
    
    # Тест 3: Ответили на все вопросы, но 2 неправильно
    print("\n--- Тест 3: Ответили на все вопросы, 2 неправильно ---")
    answered_set = {0, 1, 2, 3, 4}  # Ответили на все вопросы
    wrong_set = {1, 3}              # Вопросы 1 и 3 неправильные
    
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    
    print(f"Всего вопросов: {total_questions}")
    print(f"Отвеченные: {len(answered_set)}")
    print(f"Неотвеченные: {unanswered}")
    print(f"Ошибочные: {len(wrong_set)}")
    print(f"Оставшихся всего: {remaining_total}")
    print(f"Кнопка: {'🔁 Другой вопрос (2)' if remaining_total > 0 else '🔁 Другой вопрос'}")
    
    # Тест 4: Все вопросы отвечены правильно
    print("\n--- Тест 4: Все вопросы отвечены правильно ---")
    answered_set = {0, 1, 2, 3, 4}  # Ответили на все вопросы
    wrong_set = set()               # Нет ошибочных
    
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    
    print(f"Всего вопросов: {total_questions}")
    print(f"Отвеченные: {len(answered_set)}")
    print(f"Неотвеченные: {unanswered}")
    print(f"Ошибочные: {len(wrong_set)}")
    print(f"Оставшихся всего: {remaining_total}")
    print(f"Кнопка: {'🔁 Другой вопрос (0)' if remaining_total > 0 else '🔁 Другой вопрос'}")
    print(f"Кнопка 'Ещё вопрос' должна ПРОПАСТЬ!")
    
    # Тест 5: Симуляция прогресса - счетчик должен убывать
    print("\n--- Тест 5: Симуляция прогресса ---")
    print("Шаг 1: Ответили на вопрос 0 (правильно)")
    answered_set = {0}
    wrong_set = set()
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    print(f"  Оставшихся: {remaining_total} (должно быть 4)")
    
    print("Шаг 2: Ответили на вопрос 1 (неправильно)")
    answered_set = {0, 1}
    wrong_set = {1}
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    print(f"  Оставшихся: {remaining_total} (должно быть 4)")
    
    print("Шаг 3: Ответили на вопрос 2 (правильно)")
    answered_set = {0, 1, 2}
    wrong_set = {1}
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    print(f"  Оставшихся: {remaining_total} (должно быть 3)")
    
    print("Шаг 4: Ответили на вопрос 3 (правильно)")
    answered_set = {0, 1, 2, 3}
    wrong_set = {1}
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    print(f"  Оставшихся: {remaining_total} (должно быть 2)")
    
    print("Шаг 5: Ответили на вопрос 4 (правильно)")
    answered_set = {0, 1, 2, 3, 4}
    wrong_set = {1}
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    print(f"  Оставшихся: {remaining_total} (должно быть 1)")
    
    print("Шаг 6: Исправили ошибку в вопросе 1 (правильно)")
    answered_set = {0, 1, 2, 3, 4}
    wrong_set = set()
    unanswered = total_questions - len(answered_set)
    remaining_total = unanswered + len(wrong_set)
    print(f"  Оставшихся: {remaining_total} (должно быть 0)")
    print(f"  Кнопка 'Ещё вопрос' должна ПРОПАСТЬ!")
    
    print("\n✅ Тесты завершены!")

if __name__ == "__main__":
    test_fixed_remaining_questions_logic()
