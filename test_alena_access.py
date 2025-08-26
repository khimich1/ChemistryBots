#!/usr/bin/env python3
"""
Скрипт для тестирования доступа @AlenaSaintly к групповому тарифу
"""

import sys
import os

# Добавляем путь к govr_bot
current_dir = os.path.dirname(os.path.abspath(__file__))
govr_path = os.path.join(current_dir, "govr_bot")
sys.path.append(govr_path)

def test_alena_access():
    """Тестирует доступ @AlenaSaintly к групповому тарифу"""
    
    alena_id = 804667709  # ID @AlenaSaintly
    
    print("🧪 Тестирование доступа @AlenaSaintly к групповому тарифу")
    print("=" * 60)
    print(f"👤 ID @AlenaSaintly: {alena_id}")
    print(f"👤 Username: AlenaSaintly")
    print(f"👤 Имя: 📖 Начала химии")
    
    try:
        from bot.services.teacher_access import (
            is_student_approved_by_teacher,
            can_access_group_tariff,
            get_group_access_status
        )
        
        print("\n📊 Проверка статуса доступа:")
        print("-" * 50)
        
        # Проверяем одобрение преподавателем
        is_approved = is_student_approved_by_teacher(alena_id)
        print(f"✅ Одобрен преподавателем: {'Да' if is_approved else 'Нет'}")
        
        # Проверяем доступ к групповому тарифу
        can_access = can_access_group_tariff(alena_id)
        print(f"🔓 Может получить доступ к групповому тарифу: {'Да' if can_access else 'Нет'}")
        
        # Получаем полный статус
        status = get_group_access_status(alena_id)
        print(f"📊 Статус доступа:")
        print(f"   - Имеет групповой план: {'Да' if status['has_group_plan'] else 'Нет'}")
        print(f"   - Одобрен преподавателем: {'Да' if status['is_approved'] else 'Нет'}")
        print(f"   - Текущий план: {status['current_plan']}")
        print(f"   - Может получить доступ: {'Да' if status['can_access'] else 'Нет'}")
        
        print("\n" + "=" * 60)
        print("🎯 Демонстрация интерфейса govr_bot:")
        print("-" * 50)
        
        if status['has_group_plan'] and status['is_approved']:
            print("✅ В govr_bot будет показана кнопка:")
            print("   👨‍🏫 Подписка на бота при занятии с преподавателем — 390 ₽/мес")
        elif status['has_group_plan'] and not status['is_approved']:
            print("⏳ В govr_bot будет показана кнопка:")
            print("   📞 Записаться на бесплатное занятие")
        else:
            print("❌ В govr_bot не будет показана кнопка группового тарифа")
        
        print("\n" + "=" * 60)
        print("✅ Тест завершен!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_alena_access()

