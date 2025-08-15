import sqlite3
import os
from pathlib import Path

def extract_audio_from_db():
    """Извлекает аудио из базы данных prepared_lectures.db"""
    
    # Создаём папку аудио-конспекты в govr_bot
    audio_folder = Path("govr_bot/аудио-конспекты")
    audio_folder.mkdir(exist_ok=True)
    
    print(f"Аудио будет сохранено в: {audio_folder.absolute()}")
    
    db_path = "govr_bot/bot/prepared_lectures.db"
    
    if not os.path.exists(db_path):
        print(f"Файл {db_path} не найден!")
        return
    
    try:
        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            
            # Получаем все записи с аудио
            c.execute("""
                SELECT topic, chunk_idx, tts_audio, tts_audio_format, tts_voice, duration_ms
                FROM prepared_lectures 
                WHERE tts_audio IS NOT NULL AND tts_audio != ''
                ORDER BY topic, chunk_idx
            """)
            
            records = c.fetchall()
            print(f"Найдено {len(records)} записей с аудио")
            
            if not records:
                print("Аудио не найдено в базе данных!")
                return
            
            extracted_count = 0
            
            for topic, chunk_idx, audio_blob, audio_format, voice, duration in records:
                if not audio_blob:
                    continue
                
                # Создаём безопасное имя файла
                safe_topic = "".join(c for c in topic if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_topic = safe_topic.replace(' ', '_')
                
                # Определяем расширение файла
                if audio_format:
                    ext = audio_format.lower()
                    if ext not in ['ogg', 'mp3', 'wav', 'm4a']:
                        ext = 'ogg'  # по умолчанию
                else:
                    ext = 'ogg'
                
                # Формируем имя файла
                filename = f"{safe_topic}_chunk_{chunk_idx:03d}.{ext}"
                filepath = audio_folder / filename
                
                # Сохраняем аудио
                try:
                    with open(filepath, 'wb') as f:
                        f.write(audio_blob)
                    
                    extracted_count += 1
                    print(f"✓ {filename} ({len(audio_blob)} байт, {duration}ms)")
                    
                except Exception as e:
                    print(f"✗ Ошибка сохранения {filename}: {e}")
            
            print(f"\n✅ Извлечено {extracted_count} аудио-файлов в папку: {audio_folder.absolute()}")
            
            # Показываем статистику по темам
            c.execute("""
                SELECT topic, COUNT(*) as count
                FROM prepared_lectures 
                WHERE tts_audio IS NOT NULL AND tts_audio != ''
                GROUP BY topic
                ORDER BY count DESC
            """)
            
            topic_stats = c.fetchall()
            print(f"\n📊 Статистика по темам:")
            for topic, count in topic_stats:
                print(f"  - {topic}: {count} файлов")
                
    except Exception as e:
        print(f"Ошибка при работе с базой данных: {e}")

if __name__ == "__main__":
    extract_audio_from_db()
