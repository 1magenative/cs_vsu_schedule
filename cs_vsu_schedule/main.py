import asyncio
import os
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database
from parser import parser
import uvicorn
from webapp.app import app
from fastapi import Request

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"[WEB] Запрос: {request.method} {request.url}")
    response = await call_next(request)
    return response

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except ValueError:
    ADMIN_ID = 0

try:
    REPORTS_CHAT_ID = int(os.getenv("REPORTS_CHAT_ID", ADMIN_ID))
except ValueError:
    REPORTS_CHAT_ID = ADMIN_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

class Registration(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_subgroup = State()

class ReportState(StatesGroup):
    waiting_for_report = State()

# --- Вспомогательные функции ---

def get_main_keyboard():
    keyboard = [
        [KeyboardButton(text="📅 Понедельник"), KeyboardButton(text="📅 Вторник")],
        [KeyboardButton(text="📅 Среда"), KeyboardButton(text="📅 Четверг")],
        [KeyboardButton(text="📅 Пятница"), KeyboardButton(text="📅 Суббота")],
        [KeyboardButton(text="📌 На сегодня"), KeyboardButton(text="➡️ На завтра")],
        [KeyboardButton(text="🗓 Расписание на неделю")],
        [KeyboardButton(text="📱 Открыть Mini App", web_app=types.WebAppInfo(url=os.getenv("WEBAPP_URL", "http://localhost:8000")))],
        [KeyboardButton(text="⚙️ Режим"), KeyboardButton(text="🆘 Неправильное расписание?")],
        [KeyboardButton(text="👤 Мой профиль")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def get_display_week_type(for_date: datetime):
    current_type = await database.get_week_type()
    now = datetime.now()
    current_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    target_monday = (for_date - timedelta(days=for_date.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    
    if target_monday > current_monday:
        return 1 - current_type
    return current_type

# --- Обработчики ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_data = await database.get_user_data(message.from_user.id)
    if user_data:
        await message.answer(
            f"Привет! Ты уже зарегистрирован.\n🎓 {user_data[0]}, {user_data[1]}, подгруппа {user_data[2]}", 
            reply_markup=get_main_keyboard()
        )
    else:
        await start_registration(message, state)

async def start_registration(message: types.Message, state: FSMContext):
    courses = parser.get_courses()
    builder = InlineKeyboardBuilder()
    for course in courses:
        builder.button(text=course, callback_data=f"course_{course}")
    builder.adjust(1)
    await message.answer("Выбери свой курс:", reply_markup=builder.as_markup())
    await state.set_state(Registration.choosing_course)

@dp.callback_query(Registration.choosing_course, F.data.startswith("course_"))
async def process_course(callback: types.CallbackQuery, state: FSMContext):
    course = callback.data.split("_")[1]
    await state.update_data(course=course)
    groups = parser.get_groups(course)
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.button(text=str(group), callback_data=f"group_{group}")
    builder.adjust(3)
    await callback.message.edit_text(f"Курс: {course}. Выбери группу:", reply_markup=builder.as_markup())
    await state.set_state(Registration.choosing_group)

@dp.callback_query(Registration.choosing_group, F.data.startswith("group_"))
async def process_group(callback: types.CallbackQuery, state: FSMContext):
    group = callback.data.split("_")[1]
    await state.update_data(group=group)
    builder = InlineKeyboardBuilder()
    builder.button(text="1 подгруппа", callback_data="subgroup_1")
    builder.button(text="2 подгруппа", callback_data="subgroup_2")
    builder.adjust(2)
    await callback.message.edit_text(f"Группа: {group}. Выбери подгруппу:", reply_markup=builder.as_markup())
    await state.set_state(Registration.choosing_subgroup)

@dp.callback_query(Registration.choosing_subgroup, F.data.startswith("subgroup_"))
async def process_subgroup(callback: types.CallbackQuery, state: FSMContext):
    subgroup = callback.data.split("_")[1]
    data = await state.get_data()
    await database.save_user_data(callback.from_user.id, data['course'], data['group'], subgroup)
    await state.clear()
    await callback.message.answer(f"Регистрация завершена!\n🎓 {data['course']}, {data['group']}, подгруппа {subgroup}", 
                                reply_markup=get_main_keyboard())
    await callback.answer()

def apply_mode_transformations(subjects, mode):
    new_subjects = []
    for s in subjects:
        new_s = s
        if mode == "poxui":
            new_s = re.sub(r"Физическая культура.*", "Купить физру", new_s)
            new_s = new_s.replace("_Нет пары_", "Похуй, домой")
            new_s = new_s.replace("Нет пары", "Похуй, домой")
        elif mode == "пивко":
            new_s = re.sub(r"Физическая культура.*", "По пивку и 3км", new_s)
            new_s = new_s.replace("_Нет пары_", "По пивку, чилл")
            new_s = new_s.replace("Нет пары", "По пивку, чилл")
        new_subjects.append(new_s)
    return new_subjects

async def get_schedule_text(user_id, target_date: datetime, day_name: str = None):
    user_data = await database.get_user_data(user_id)
    if not user_data: return "Сначала пройди регистрацию /start"
    
    course, group, subgroup, mode = user_data
    week_type = await get_display_week_type(target_date)
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    
    if not day_name:
        days_map = {0:"Понедельник", 1:"Вторник", 2:"Среда", 3:"Четверг", 4:"Пятница", 5:"Суббота", 6:"Воскресенье"}
        day_name = days_map.get(target_date.weekday())

    if day_name == "Воскресенье":
        text = f"📅 *{day_name}* ({week_name})\n"
        if mode == "poxui": text += "🎉 Похуй, домой"
        elif mode == "пивко": text += "🎉 По пивку, чилл"
        else: text += "🎉 Пар нет, отдыхай!"
        return text

    schedule = parser.get_schedule(course, group, subgroup, week_type)
    day_schedule = schedule.get(day_name) if isinstance(schedule, dict) else None
    
    text = f"📅 *{day_name}* ({week_name})\n"
    text += "─" * 15 + "\n\n"
    if not day_schedule:
        if mode == "poxui": text += "🎉 Похуй, домой"
        elif mode == "пивко": text += "🎉 По пивку, чилл"
        else: text += "🎉 Пар нет, отдыхай!"
    else:
        day_schedule = apply_mode_transformations(day_schedule, mode)
        text += "\n\n".join(day_schedule)
    return text

@dp.message(F.text.regexp(r"(📅 (Понедельник|Вторник|Среда|Четверг|Пятница|Суббота))"))
async def show_day_schedule(message: types.Message):
    day = message.text.split(" ")[1]
    text = await get_schedule_text(message.from_user.id, datetime.now(), day)
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📌 На сегодня")
async def show_today(message: types.Message):
    text = await get_schedule_text(message.from_user.id, datetime.now())
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "➡️ На завтра")
async def show_tomorrow(message: types.Message):
    tomorrow = datetime.now() + timedelta(days=1)
    text = await get_schedule_text(message.from_user.id, tomorrow)
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🗓 Расписание на неделю")
async def show_week_schedule(message: types.Message):
    user_data = await database.get_user_data(message.from_user.id)
    if not user_data:
        await message.answer("Сначала пройди регистрацию /start")
        return
    now = datetime.now()
    display_date = now + timedelta(days=1) if now.weekday() == 6 else now
    week_type = await get_display_week_type(display_date)
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    
    course, group, subgroup, mode = user_data
    schedule = parser.get_schedule(course, group, subgroup, week_type)
    
    header = f"🗓 *РАСПИСАНИЕ НА НЕДЕЛЮ* ({week_name})\n🎓 {course}, {group}, подгруппа {subgroup}\n" + "═" * 20 + "\n\n"
    await message.answer(header, parse_mode="Markdown")
    
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
    for day in days:
        day_schedule = schedule.get(day)
        text = f"🔸 *{day}*\n"
        if not day_schedule:
            if mode == "poxui": text += "— Похуй, домой\n\n"
            elif mode == "пивко": text += "— По пивку, чилл\n\n"
            else: text += "— Пар нет\n\n"
        else:
            day_schedule = apply_mode_transformations(day_schedule, mode)
            text += "\n".join([s.replace('*', '') for s in day_schedule]) + "\n\n"
        await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "👤 Мой профиль")
async def show_profile(message: types.Message):
    user_data = await database.get_user_data(message.from_user.id)
    if user_data:
        text = f"👤 *Мой профиль*\n\nКурс: {user_data[0]}\nГруппа: {user_data[1]}\nПодгруппа: {user_data[2]}"
        builder = InlineKeyboardBuilder()
        builder.button(text="Изменить данные", callback_data="re_register")
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer("Ты еще не зарегистрирован.")

@dp.callback_query(F.data == "re_register")
async def re_register(callback: types.CallbackQuery, state: FSMContext):
    await start_registration(callback.message, state)
    await callback.answer()

@dp.message(F.text == "⚙️ Режим")
async def show_mode_menu(message: types.Message):
    current_mode = await database.get_user_mode(message.from_user.id)
    builder = InlineKeyboardBuilder()
    modes = [("обычный", "обычный"), ("poxui", "poxui"), ("пивко", "пивко")]
    for mode_id, mode_name in modes:
        status = " ✅" if current_mode == mode_id else ""
        builder.button(text=f"{mode_name}{status}", callback_data=f"set_mode_{mode_id}")
    builder.adjust(1)
    await message.answer(f"Выберите режим (текущий: {current_mode}):", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("set_mode_"))
async def set_mode_cb(callback: types.CallbackQuery):
    mode = callback.data.split("_")[2]
    await database.set_user_mode(callback.from_user.id, mode)
    await callback.message.edit_text(f"✅ Режим изменен на: *{mode}*", parse_mode="Markdown")
    await callback.answer()

@dp.message(F.text == "🆘 Неправильное расписание?")
async def report_start(message: types.Message, state: FSMContext):
    await message.answer("Опишите, что именно неправильно в расписании. Я передам это администратору.")
    await state.set_state(ReportState.waiting_for_report)

@dp.message(ReportState.waiting_for_report)
async def process_report(message: types.Message, state: FSMContext):
    user_info = f"ID: {message.from_user.id}\nИмя: {message.from_user.full_name}"
    if message.from_user.username: user_info += f" (@{message.from_user.username})"
    await database.add_report(message.from_user.id, message.from_user.full_name, message.text)
    await bot.send_message(REPORTS_CHAT_ID, f"🔔 *НОВАЯ ЖАЛОБА*\n\n{user_info}\n\nТекст:\n{message.text}", parse_mode="Markdown")
    await message.answer("✅ Ваше сообщение отправлено администратору. Спасибо!")
    await state.clear()

@dp.message(F.reply_to_message, (F.from_user.id == ADMIN_ID) | (F.chat.id == REPORTS_CHAT_ID))
async def handle_admin_reply(message: types.Message):
    reply_text = message.reply_to_message.text
    if reply_text and "ID: " in reply_text:
        try:
            target_user_id = int(reply_text.split("ID: ")[1].split("\n")[0])
            await bot.send_message(target_user_id, f"📩 *Ответ от администратора:*\n\n{message.text}", parse_mode="Markdown")
            await message.answer("✅ Ответ отправлен пользователю.")
        except Exception as e:
            await message.answer(f"❌ Ошибка при отправке ответа: {e}")

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    week_type = await database.get_week_type()
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Сменить тип недели", callback_data="toggle_week")
    builder.button(text="📥 Обновить таблицу сейчас", callback_data="admin_update_data")
    builder.button(text="📋 Список открытых жалоб", callback_data="view_reports")
    builder.adjust(1)
    await message.answer(f"⚙️ *Админ-панель*\nТекущая неделя: {week_name}", reply_markup=builder.as_markup(), parse_mode="Markdown")

# --- Задачи по расписанию ---
async def auto_weekly_task():
    new_type = await database.toggle_week_type()
    parser.update_data()
    logger.info(f"Выполнена еженедельная задача: тип недели {new_type}")

async def start_bot():
    await database.init_db()
    logger.info(f"Запуск бота. ID администратора: {ADMIN_ID}")
    
    await bot.set_chat_menu_button(
        menu_button=types.MenuButtonWebApp(
            text="Расписание",
            web_app=types.WebAppInfo(url=os.getenv("WEBAPP_URL", "http://localhost:8000"))
        )
    )
    
    scheduler.add_job(auto_weekly_task, 'cron', day_of_week='mon', hour=0, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

async def start_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    bot_task = asyncio.create_task(start_bot())
    server_task = asyncio.create_task(start_server())
    await asyncio.gather(bot_task, server_task)

if __name__ == "__main__":
    asyncio.run(main())
