import aiosqlite
import os

DB_PATH = "bot_database.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                course TEXT,
                group_num TEXT,
                subgroup TEXT,
                mode TEXT DEFAULT 'обычный'
            )
        """)
        # Миграция: добавляем колонку mode, если её нет
        try:
            await db.execute("ALTER TABLE users ADD COLUMN mode TEXT DEFAULT 'обычный'")
        except:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                text TEXT,
                status TEXT DEFAULT 'open',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Начальное значение типа недели (0 - числитель, 1 - знаменатель)
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('week_type', '0')")
        await db.commit()

async def get_user_data(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT course, group_num, subgroup, mode FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def save_user_data(user_id, course, group_num, subgroup):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (user_id, course, group_num, subgroup) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(user_id) DO UPDATE SET course=excluded.course, group_num=excluded.group_num, subgroup=excluded.subgroup", 
                         (user_id, course, group_num, subgroup))
        await db.commit()

async def get_user_mode(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT mode FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "обычный"

async def set_user_mode(user_id, mode):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET mode = ? WHERE user_id = ?", (mode, user_id))
        await db.commit()

async def add_report(user_id, user_name, text):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO reports (user_id, user_name, text) VALUES (?, ?, ?)", 
                         (user_id, user_name, text))
        await db.commit()

async def get_open_reports():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, user_id, user_name, text, timestamp FROM reports WHERE status = 'open'") as cursor:
            return await cursor.fetchall()

async def close_report(report_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reports SET status = 'closed' WHERE id = ?", (report_id,))
        await db.commit()

async def get_week_type():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'week_type'") as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

async def set_week_type(value: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('week_type', ?)", (str(value),))
        await db.commit()

async def toggle_week_type():
    current = await get_week_type()
    new_type = 1 - current
    await set_week_type(new_type)
    return new_type
