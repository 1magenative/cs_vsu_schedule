import sqlite3
from datetime import datetime

def fix_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    print("Проверка структуры базы данных...")
    
    # Проверяем колонки в таблице users
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'mode' not in columns:
        print("Добавляю колонку 'mode'...")
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN mode TEXT DEFAULT 'обычный'")
        except Exception as e: print(f"Ошибка mode: {e}")
        
    if 'last_active' not in columns:
        print("Добавляю колонку 'last_active'...")
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN last_active DATETIME")
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("UPDATE users SET last_active = ?", (now,))
        except Exception as e: print(f"Ошибка last_active: {e}")
    
    # Инициализация таблицы настроек
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('timezone_offset', '0')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_updating', '0')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('week_type', '0')")
    
    conn.commit()
    conn.close()
    print("Готово! База данных на сервере обновлена.")

if __name__ == "__main__":
    fix_db()
