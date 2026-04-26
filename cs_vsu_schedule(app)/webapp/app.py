from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import database
from parser import parser
from datetime import datetime, timedelta
from bot_instance import bot, REPORTS_CHAT_ID, ADMIN_ID # Импортируем из правильного места

app = FastAPI()

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

class UserSettingsUpdate(BaseModel):
    user_id: int
    show_timer: int
    timer_start_mode: int
    show_intra_break: int

class UserModeUpdate(BaseModel):
    user_id: int
    mode: str

class UserReport(BaseModel):
    user_id: int
    user_name: str
    text: str

@app.get("/api/search/teacher")
async def search_teacher(name: str):
    return parser.get_teacher_schedule(name)

@app.get("/api/search/rooms")
async def search_rooms(day: str, slot: str, week_type: int):
    return parser.get_free_classrooms(day, slot, week_type)

@app.get("/api/subgroups")
async def get_subgroups(course: str, group: str):
    return parser.get_subgroups(course, group)

@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int):
    await database.update_last_active(user_id)
    data = await database.get_user_data(user_id)
    week_type = await database.get_week_type()
    is_updating = await database.get_update_status()
    offset = await database.get_timezone_offset()
    
    import time
    bot_timestamp = int(time.time() + (3 + offset) * 3600)
    
    from datetime import datetime, timedelta, timezone
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3 + offset)
    display_week = week_type
    is_next_week = False
    if msk_now.weekday() == 6:
        display_week = 1 - week_type
        is_next_week = True

    if not data:
        return {
            "registered": False, "week_type": week_type, "display_week_type": display_week,
            "is_next_week": is_next_week, "is_updating": is_updating, 
            "timezone_offset": offset, "server_time": bot_timestamp
        }
    return {
        "registered": True, "course": data[0], "group": data[1], "subgroup": data[2],
        "mode": data[3], "show_timer": data[4], "timer_start_mode": data[5], "show_intra_break": data[6],
        "week_type": week_type, "display_week_type": display_week, "is_next_week": is_next_week,
        "is_updating": is_updating, "timezone_offset": offset, "server_time": bot_timestamp
    }

@app.post("/api/update_profile")
async def update_profile(profile: UserProfileUpdate):
    await database.save_user_data(profile.user_id, profile.course, profile.group_num, profile.subgroup)
    return {"status": "ok"}

@app.post("/api/update_settings")
async def update_settings(settings: UserSettingsUpdate):
    await database.update_user_settings(settings.user_id, settings.show_timer, settings.timer_start_mode, settings.show_intra_break)
    return {"status": "ok"}

@app.post("/api/update_mode")
async def update_mode(mode_update: UserModeUpdate):
    await database.set_user_mode(mode_update.user_id, mode_update.mode)
    return {"status": "ok"}

@app.post("/api/report")
async def submit_report(report: UserReport):
    await database.add_report(report.user_id, report.user_name, report.text)
    user_info = f"ID: {report.user_id}\nИмя: {report.user_name}"
    try:
        await bot.send_message(REPORTS_CHAT_ID, f"🔔 <b>НОВАЯ ЖАЛОБА (из Mini App)</b>\n\n{user_info}\n\nТекст:\n{report.text}", parse_mode="HTML")
    except:
        try:
            await bot.send_message(ADMIN_ID, f"🔔 <b>НОВАЯ ЖАЛОБА (в личку)</b>\n\n{user_info}\n\nТекст:\n{report.text}", parse_mode="HTML")
        except Exception as e:
            print(f"Ошибка отправки: {e}")
    return {"status": "ok"}

@app.get("/api/schedule/{user_id}")
async def get_schedule(user_id: int, day: str = None):
    if await database.get_update_status(): return {"updating": True, "message": "⚠️ Расписание обновляется."}
    user_data = await database.get_user_data(user_id)
    if not user_data: raise HTTPException(status_code=404, detail="User not registered")
    course, group, subgroup, mode = user_data[0], user_data[1], user_data[2], user_data[3]
    offset = await database.get_timezone_offset()
    from datetime import datetime, timedelta, timezone
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3 + offset)
    current_week_type = await database.get_week_type()
    if msk_now.weekday() == 6: current_week_type = 1 - current_week_type
    schedule = parser.get_schedule(course, group, subgroup, current_week_type)
    import re
    def apply_mode_transformations(subjects, mode):
        new_subjects = []
        for s in subjects:
            new_s = s
            if mode == "po***":
                new_s = re.sub(r"Физическая культура.*", "Купить физру", new_s)
                new_s = new_s.replace("_Нет пары_", "Похуй, домой").replace("Нет пары", "Похуй, домой")
            elif mode == "пивко":
                new_s = re.sub(r"Физическая культура.*", "По пивку и 3км", new_s)
                new_s = new_s.replace("_Нет пары_", "По пивку, чилл").replace("Нет пары", "По пивку, чилл")
            new_subjects.append(new_s)
        return new_subjects
    if isinstance(schedule, dict):
        for d in schedule: schedule[d] = apply_mode_transformations(schedule[d], mode)
    return {day: schedule.get(day, [])} if day else schedule

@app.get("/api/meta")
async def get_meta():
    courses = parser.get_courses()
    meta = {}
    for course in courses: meta[course] = parser.get_groups(course)
    return meta

app.mount("/", StaticFiles(directory="webapp/static", html=True), name="static")
