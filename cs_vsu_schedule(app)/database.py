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
                mode TEXT DEFAULT 'обычный',
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
                show_timer INTEGER DEFAULT 1,
                timer_start_mode INTEGER DEFAULT 0,
                show_intra_break INTEGER DEFAULT 0
            )
        """)
        # Миграции
        try: await db.execute("ALTER TABLE users ADD COLUMN mode TEXT DEFAULT 'обычный'")
        except: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN last_active DATETIME DEFAULT CURRENT_TIMESTAMP")
        except: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN show_timer INTEGER DEFAULT 1")
        except: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN timer_start_mode INTEGER DEFAULT 0")
        except: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN show_intra_break INTEGER DEFAULT 0")
        except: pass

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
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('week_type', '0')")
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_updating', '0')")
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('timezone_offset', '0')")
        await db.commit()

async def get_timezone_offset():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'timezone_offset'") as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

async def set_timezone_offset(value: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('timezone_offset', ?)", (str(value),))
        await db.commit()

async def update_last_active(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total = (await cursor.fetchone())[0]
        # Используем datetime('now', 'start of day') для корректного подсчета за сегодня
        async with db.execute("SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', 'start of day')") as cursor:
            daily = (await cursor.fetchone())[0]
        return {"total": total, "daily": daily}

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_user_data(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT course, group_num, subgroup, mode, show_timer, timer_start_mode, show_intra_break FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def update_user_settings(user_id, show_timer, timer_start_mode, show_intra_break):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE users SET 
            show_timer = ?, 
            timer_start_mode = ?, 
            show_intra_break = ? 
            WHERE user_id = ?
        """, (show_timer, timer_start_mode, show_intra_break, user_id))
        await db.commit()

async def save_user_data(user_id, course, group_num, subgroup):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (user_id, course, group_num, subgroup, last_active) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                         "ON CONFLICT(user_id) DO UPDATE SET course=excluded.course, group_num=excluded.group_num, subgroup=excluded.subgroup, last_active=CURRENT_TIMESTAMP", 
                         (user_id, course, group_num, subgroup))
        await db.commit()

async def get_user_mode(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT mode FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "обычный"

async def set_user_mode(user_id, mode):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET mode = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (mode, user_id))
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

async def get_update_status():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'is_updating'") as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

async def set_update_status(value: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('is_updating', ?)", (str(value),))
        await db.commit()

async def toggle_update_status():
    current = await get_update_status()
    new_status = 1 - current
    await set_update_status(new_status)
    return new_status
