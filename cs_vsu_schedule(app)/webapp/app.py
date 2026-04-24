from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import database
from parser import parser
from datetime import datetime, timedelta

app = FastAPI()

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserProfileUpdate(BaseModel):
    user_id: int
    course: str
    group_num: str
    subgroup: str

class UserModeUpdate(BaseModel):
    user_id: int
    mode: str

class UserReport(BaseModel):
    user_id: int
    user_name: str
    text: str

@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int):
    await database.update_last_active(user_id)
    data = await database.get_user_data(user_id)
    week_type = await database.get_week_type()
    is_updating = await database.get_update_status()
    offset = await database.get_timezone_offset()
    
    from datetime import datetime, timedelta
    server_now = datetime.now() + timedelta(hours=offset)
    server_timestamp = int(server_now.timestamp())

    if not data:
        return {
            "registered": False, 
            "week_type": week_type, 
            "is_updating": is_updating, 
            "timezone_offset": offset,
            "server_time": server_timestamp
        }
    return {
        "registered": True,
        "course": data[0],
        "group": data[1],
        "subgroup": data[2],
        "mode": data[3],
        "week_type": week_type,
        "is_updating": is_updating,
        "timezone_offset": offset,
        "server_time": server_timestamp
    }

@app.post("/api/update_profile")
async def update_profile(profile: UserProfileUpdate):
    await database.save_user_data(profile.user_id, profile.course, profile.group_num, profile.subgroup)
    return {"status": "ok"}

@app.post("/api/update_mode")
async def update_mode(mode_update: UserModeUpdate):
    await database.set_user_mode(mode_update.user_id, mode_update.mode)
    return {"status": "ok"}

@app.post("/api/report")
async def submit_report(report: UserReport):
    await database.add_report(report.user_id, report.user_name, report.text)
    try:
        from main import bot, REPORTS_CHAT_ID
        await bot.send_message(REPORTS_CHAT_ID, f"🔔 *НОВАЯ ЖАЛОБА (из Mini App)*\n\nID: {report.user_id}\nИмя: {report.user_name}\n\nТекст:\n{report.text}", parse_mode="Markdown")
    except Exception as e:
        print(f"Не удалось отправить жалобу в Telegram: {e}")
    return {"status": "ok"}

@app.get("/api/schedule/{user_id}")
async def get_schedule(user_id: int, day: str = None):
    if await database.get_update_status():
        return {"updating": True, "message": "⚠️ Расписание обновляется. Зайдите позже."}

    user_data = await database.get_user_data(user_id)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not registered")
    
    course, group, subgroup, mode = user_data
    week_type = await database.get_week_type() # Simplified for web app, or we can calculate like in bot
    
    # Calculate week type for today
    now = datetime.now()
    # In bot_main.py: get_display_week_type(for_date)
    # Let's import it or replicate logic
    current_week_type = await database.get_week_type()
    
    schedule = parser.get_schedule(course, group, subgroup, current_week_type)
    
    import re
    def apply_mode_transformations(subjects, mode):
        new_subjects = []
        for s in subjects:
            new_s = s
            if mode == "po***":
                new_s = re.sub(r"Физическая культура.*", "Купить физру", new_s)
                new_s = new_s.replace("_Нет пары_", "Похуй, домой")
                new_s = new_s.replace("Нет пары", "Похуй, домой")
            elif mode == "пивко":
                new_s = re.sub(r"Физическая культура.*", "По пивку и 3км", new_s)
                new_s = new_s.replace("_Нет пары_", "По пивку, чилл")
                new_s = new_s.replace("Нет пары", "По пивку, чилл")
            new_subjects.append(new_s)
        return new_subjects
        
    if isinstance(schedule, dict):
        for d in schedule:
            schedule[d] = apply_mode_transformations(schedule[d], mode)
    
    if day:
        return {day: schedule.get(day, [])}
    return schedule

@app.get("/api/meta")
async def get_meta():
    courses = parser.get_courses()
    meta = {}
    for course in courses:
        meta[course] = parser.get_groups(course)
    return meta

# Serve static files
app.mount("/", StaticFiles(directory="webapp/static", html=True), name="static")
