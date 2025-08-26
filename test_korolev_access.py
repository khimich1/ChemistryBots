#!/usr/bin/env python3
"""
Скрипт для проверки доступа Алексея Королева
"""

import sys
import os

# Добавляем путь к govr_bot
current_dir = os.path.dirname(os.path.abspath(__file__))
govr_path = os.path.join(current_dir, "govr_bot")
sys.path.append(govr_path)

def test_korolev_access():
    """Проверяет доступ Алексея Королева"""
    
    print("👤 Проверка доступа Алексея Королева")
    print("=" * 50)
    
    try:
        from bot.services.teacher_access import get_group_access_status
        
        korolev_id = 399462447  # ID Алексея Королева
        
        print(f"👤 ID Алексея Королева: {korolev_id}")
        
        # Проверяем статус доступа
        status = get_group_access_status(korolev_id)
        
        print(f"\n📊 Статус доступа:")
        print(f"   План: {status['plan']}")
        print(f"   Одобрен преподавателем: {status['approved_by_teacher']}")
        print(f"   Может получить доступ: {status['can_access']}")
        print(f"   Причина: {status['reason']}")
        
        if status['can_access']:
            print("\n✅ Алексей Королев теперь может получить доступ к групповому тарифу!")
        else:
            print(f"\n❌ Алексей Королев не может получить доступ: {status['reason']}")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    test_korolev_access()
