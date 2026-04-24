import sqlite3
from datetime import datetime

def fix_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    print("Проверка структуры базы данных...")
    
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'mode' not in columns:
        print("Добавляю колонку 'mode'...")
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN mode TEXT DEFAULT 'обычный'")
        except Exception as e:
            print(f"Ошибка при добавлении 'mode': {e}")
            
    if 'last_active' not in columns:
        print("Добавляю колонку 'last_active'...")
        try:
            # В SQLite нельзя использовать CURRENT_TIMESTAMP как DEFAULT при ALTER TABLE
            # Добавляем просто колонку
            cursor.execute("ALTER TABLE users ADD COLUMN last_active DATETIME")
            # Заполняем текущим временем
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("UPDATE users SET last_active = ?", (now,))
            print("Колонка 'last_active' успешно добавлена и заполнена.")
        except Exception as e:
            print(f"Ошибка при добавлении 'last_active': {e}")
            
    conn.commit()
    conn.close()
    print("Готово! База данных обновлена.")

if __name__ == "__main__":
    fix_db()
