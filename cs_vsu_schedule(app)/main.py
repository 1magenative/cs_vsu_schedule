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

# --- Состояния FSM ---

class Registration(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_subgroup = State()

class ReportState(StatesGroup):
    waiting_for_report = State()

class TeacherSearch(StatesGroup):
    waiting_for_name = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

class FreeRoomSearch(StatesGroup):
    choosing_day_week = State()
    choosing_slot = State()

# --- Вспомогательные функции ---

async def track_activity(user_id):
    await database.update_last_active(user_id)

async def get_now():
    offset = await database.get_timezone_offset()
    return datetime.now() + timedelta(hours=offset)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton(text="📅 Понедельник"), KeyboardButton(text="📅 Вторник")],
        [KeyboardButton(text="📅 Среда"), KeyboardButton(text="📅 Четверг")],
        [KeyboardButton(text="📅 Пятница"), KeyboardButton(text="📅 Суббота")],
        [KeyboardButton(text="📌 На сегодня"), KeyboardButton(text="➡️ На завтра")],
        [KeyboardButton(text="🗓 Расписание на неделю")],
        [KeyboardButton(text="🔍 Поиск")],
        [KeyboardButton(text="📱 Открыть Mini App", web_app=types.WebAppInfo(url=os.getenv("WEBAPP_URL", "http://localhost:8000")))],
        [KeyboardButton(text="⚙️ Режим"), KeyboardButton(text="🆘 Неправильное расписание?")],
        [KeyboardButton(text="👤 Мой профиль")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def get_display_week_type(for_date: datetime):
    current_type = await database.get_week_type()
    now = await get_now()
    current_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    target_monday = (for_date - timedelta(days=for_date.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    
    if target_monday > current_monday:
        return 1 - current_type
    return current_type

# --- Обработчики ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await track_activity(message.from_user.id)
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

async def get_schedule_text(user_id, target_date: datetime, day_name: str = None):
    if await database.get_update_status():
        return "⚠️ *ВНИМАНИЕ*\n\nВ данный момент расписание обновляется. Пожалуйста, зайдите позже или следите за новостями в канале."

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
        if mode == "po***": text += "🎉 Похуй, домой"
        elif mode == "пивко": text += "🎉 По пивку, чилл"
        else: text += "🎉 Пар нет, отдыхай!"
        return text

    schedule = parser.get_schedule(course, group, subgroup, week_type)
    day_schedule = schedule.get(day_name) if isinstance(schedule, dict) else None
    
    text = f"📅 *{day_name}* ({week_name})\n"
    text += "─" * 15 + "\n\n"
    if not day_schedule:
        if mode == "po***": text += "🎉 Похуй, домой"
        elif mode == "пивко": text += "🎉 По пивку, чилл"
        else: text += "🎉 Пар нет, отдыхай!"
    else:
        day_schedule = apply_mode_transformations(day_schedule, mode)
        text += "\n\n".join(day_schedule)
    return text

@dp.message(F.text == "🔍 Поиск")
async def show_search_menu(message: types.Message):
    await track_activity(message.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.button(text="👨‍🏫 Преподаватель", callback_data="search_teacher")
    builder.button(text="🚪 Свободные аудитории", callback_data="search_free_rooms")
    builder.adjust(1)
    await message.answer("Что будем искать?", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "search_teacher")
async def teacher_search_start_cb(callback: types.CallbackQuery, state: FSMContext):
    await track_activity(callback.from_user.id)
    await callback.message.answer("Введите фамилию преподавателя (или часть фамилии):")
    await state.set_state(TeacherSearch.waiting_for_name)
    await callback.answer()

@dp.callback_query(F.data == "search_free_rooms")
async def free_rooms_day_week_cb(callback: types.CallbackQuery, state: FSMContext):
    await track_activity(callback.from_user.id)
    now = await get_now()
    week_type = await get_display_week_type(now)
    
    # Короткие метки для текущего момента
    week_label = "Числитель" if week_type == 0 else "Знаменатель"
    day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][now.weekday()]
    
    builder = InlineKeyboardBuilder()
    # Кнопка "На текущий момент"
    builder.button(text=f"✨ СЕЙЧАС ({day_name}, {week_label})", callback_data=f"roomdw_curr")
    
    # Список дней с выбором недели
    days = [
        ("Понедельник", "Пн"), ("Вторник", "Вт"), ("Среда", "Ср"), 
        ("Четверг", "Чт"), ("Пятница", "Пт"), ("Суббота", "Сб")
    ]
    
    for full_name, short_name in days:
        builder.button(text=f"{short_name} [Числитель]", callback_data=f"roomdw_{full_name}_0")
        builder.button(text=f"{short_name} [Знаменатель]", callback_data=f"roomdw_{full_name}_1")
    
    builder.adjust(1, 2)
    await callback.message.edit_text("📅 *Выбор дня и недели*\nУкажите, на когда ищем свободные аудитории:", 
                                   reply_markup=builder.as_markup(), parse_mode="Markdown")
    await state.set_state(FreeRoomSearch.choosing_day_week)
    await callback.answer()

@dp.callback_query(FreeRoomSearch.choosing_day_week, F.data.startswith("roomdw_"))
async def free_rooms_slot_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "roomdw_curr":
        now = await get_now()
        week_type = await get_display_week_type(now)
        days_map = {0:"Понедельник", 1:"Вторник", 2:"Среда", 3:"Четверг", 4:"Пятница", 5:"Суббота", 6:"Воскресенье"}
        day_name = days_map.get(now.weekday())
    else:
        parts = callback.data.split("_")
        day_name = parts[1]
        week_type = int(parts[2])
    
    await state.update_data(search_day=day_name, search_week=week_type)
    builder = InlineKeyboardBuilder()
    for slot in parser.TIME_SLOTS:
        builder.button(text=slot, callback_data=f"roomslot_{slot}")
    builder.adjust(2)
    
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    await callback.message.answer(f"Ищем на: *{day_name}* ({week_name})\nТеперь выберите временной слот:", 
                                reply_markup=builder.as_markup(), parse_mode="Markdown")
    await state.set_state(FreeRoomSearch.choosing_slot)
    await callback.answer()

@dp.callback_query(FreeRoomSearch.choosing_slot, F.data.startswith("roomslot_"))
async def process_free_rooms(callback: types.CallbackQuery, state: FSMContext):
    slot = callback.data.split("_")[1]
    data = await state.get_data()
    day_name = data.get('search_day')
    week_type = data.get('search_week')
    
    if day_name == "Воскресенье":
        await callback.message.answer("Сегодня воскресенье, все аудитории свободны!")
        await state.clear()
        return

    rooms = parser.get_free_classrooms(day_name, slot, week_type)
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    text = f"🚪 *Свободные аудитории*\n📅 {day_name} ({week_name})\n⏰ Время: {slot}\n" + "─" * 20 + "\n\n"
    if not rooms['main'] and not rooms['p']:
        text += "Все аудитории заняты! 😱"
    else:
        if rooms['main']:
            text += "*Главный корпус / 2 корпус:*\n" + ", ".join(rooms['main']) + "\n\n"
        if rooms['p']:
            text += "*Пристройка (П):*\n" + ", ".join(rooms['p']) + "\n"
    await callback.message.answer(text, parse_mode="Markdown")
    await state.clear()
    await callback.answer()

@dp.message(TeacherSearch.waiting_for_name)
async def process_teacher_search(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("Пожалуйста, введите хотя бы 3 буквы для поиска.")
        return
    results = parser.get_teacher_schedule(name)
    if not results:
        await message.answer(f"Преподаватель '{name}' не найден.")
    else:
        text = f"🔍 *Результаты поиска: {name}*\n" + "─" * 20 + "\n\n"
        for res in results:
            text += f"📅 *{res['day']}* | {res['time']}\n🏷 [{res['week_type']}]\n🎓 {res['course']}, {res['group']}\n📖 {res['subject']}\n\n"
        if len(text) > 4000:
            await message.answer(text[:4000], parse_mode="Markdown")
            await message.answer(text[4000:], parse_mode="Markdown")
        else:
            await message.answer(text, parse_mode="Markdown")
    await state.clear()

@dp.message(F.text.regexp(r"(📅 (Понедельник|Вторник|Среда|Четверг|Пятница|Суббота))"))
async def show_day_schedule(message: types.Message):
    await track_activity(message.from_user.id)
    day = message.text.split(" ")[1]
    now = await get_now()
    text = await get_schedule_text(message.from_user.id, now, day)
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📌 На сегодня")
async def show_today(message: types.Message):
    await track_activity(message.from_user.id)
    now = await get_now()
    text = await get_schedule_text(message.from_user.id, now)
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "➡️ На завтра")
async def show_tomorrow(message: types.Message):
    await track_activity(message.from_user.id)
    now = await get_now()
    tomorrow = now + timedelta(days=1)
    text = await get_schedule_text(message.from_user.id, tomorrow)
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🗓 Расписание на неделю")
async def show_week_schedule(message: types.Message):
    await track_activity(message.from_user.id)
    user_data = await database.get_user_data(message.from_user.id)
    if not user_data:
        await message.answer("Сначала пройди регистрацию /start")
        return
    now = await get_now()
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
            if mode == "po***": text += "— Похуй, домой\n\n"
            elif mode == "пивко": text += "— По пивку, чилл\n\n"
            else: text += "— Пар нет\n\n"
        else:
            day_schedule = apply_mode_transformations(day_schedule, mode)
            text += "\n".join([s.replace('*', '') for s in day_schedule]) + "\n\n"
        await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "👤 Мой профиль")
async def show_profile(message: types.Message):
    await track_activity(message.from_user.id)
    user_data = await database.get_user_data(message.from_user.id)
    if user_data:
        text = f"👤 *Мой профиль*\n\nКурс: {user_data[0]}\n{user_data[1]}\nПодгруппа: {user_data[2]}"
        builder = InlineKeyboardBuilder()
        builder.button(text="Изменить данные", callback_data="re_register")
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message.answer("Ты еще не зарегистрирован.")

@dp.callback_query(F.data == "re_register")
async def re_register(callback: types.CallbackQuery, state: FSMContext):
    await track_activity(callback.from_user.id)
    await start_registration(callback.message, state)
    await callback.answer()

@dp.message(F.text == "⚙️ Режим")
@dp.message(Command("mode"))
async def show_mode_menu(message: types.Message):
    await track_activity(message.from_user.id)
    current_mode = await database.get_user_mode(message.from_user.id)
    builder = InlineKeyboardBuilder()
    modes = [("обычный", "обычный"), ("po***", "po***"), ("пивко", "пивко")]
    for mode_id, mode_name in modes:
        status = " ✅" if current_mode == mode_id else ""
        builder.button(text=f"{mode_name}{status}", callback_data=f"set_mode_{mode_id}")
    builder.adjust(1)
    await message.answer(f"Выберите режим (текущий: {current_mode}):", reply_markup=builder.as_markup())

@dp.message(Command("usual"))
async def set_mode_usual(message: types.Message):
    await track_activity(message.from_user.id)
    await database.set_user_mode(message.from_user.id, "обычный")
    await message.answer("✅ Режим изменен на: <b>обычный</b>", parse_mode="HTML")

@dp.message(Command("po"))
@dp.message(F.text.casefold() == "po***")
async def set_mode_po_star(message: types.Message):
    await track_activity(message.from_user.id)
    await database.set_user_mode(message.from_user.id, "po***")
    await message.answer("✅ Режим изменен на: <b>po***</b>", parse_mode="HTML")

@dp.message(Command("pivko"))
async def set_mode_pivko(message: types.Message):
    await track_activity(message.from_user.id)
    await database.set_user_mode(message.from_user.id, "пивко")
    await message.answer("✅ Режим изменен на: <b>пивко</b>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("set_mode_"))
async def set_mode_cb(callback: types.CallbackQuery):
    await track_activity(callback.from_user.id)
    mode = callback.data.split("_")[2]
    await database.set_user_mode(callback.from_user.id, mode)
    await callback.message.edit_text(f"✅ Режим изменен на: <b>{mode}</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(F.text == "🆘 Неправильное расписание?")
async def report_start(message: types.Message, state: FSMContext):
    await track_activity(message.from_user.id)
    await message.answer("Опишите, что именно неправильно в расписании. Я передам это администратору.")
    await state.set_state(ReportState.waiting_for_report)

@dp.message(ReportState.waiting_for_report)
async def process_report(message: types.Message, state: FSMContext):
    await track_activity(message.from_user.id)
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
async def admin_panel(message: types.Message, edit: bool = False):
    if message.from_user.id != ADMIN_ID: return
    stats = await database.get_stats()
    week_type = await database.get_week_type()
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    is_updating = await database.get_update_status()
    offset = await database.get_timezone_offset()
    update_status_text = "🔴 Выключить режим обновления" if is_updating else "🟢 Включить режим обновления"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Сменить тип недели", callback_data="toggle_week")
    builder.button(text=update_status_text, callback_data="toggle_update_mode")
    builder.button(text="📢 Рассылка всем", callback_data="admin_broadcast")
    builder.button(text=f"⏰ Время: {'+' if offset >= 0 else ''}{offset}ч", callback_data="none")
    builder.button(text="➖ 1 час", callback_data="offset_minus")
    builder.button(text="➕ 1 час", callback_data="offset_plus")
    builder.adjust(1, 1, 1, 1, 2)
    now = await get_now()
    status_msg = f"⚙️ *Админ-панель*\n\n📊 *Статистика:*\n— Всего пользователей: {stats['total']}\n— Активны сегодня: {stats['daily']}\n\n📅 Неделя: {week_name}\n🕒 Время бота: {now.strftime('%H:%M')}\n"
    status_msg += "⚠️ *РЕЖИМ ОБНОВЛЕНИЯ ВКЛЮЧЕН*" if is_updating else "✅ Расписание доступно"
    if edit:
        try: await message.edit_text(status_msg, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except: pass
    else: await message.answer(status_msg, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("offset_"))
async def offset_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    current = await database.get_timezone_offset()
    new_offset = current + (1 if "plus" in callback.data else -1)
    await database.set_timezone_offset(new_offset)
    await admin_panel(callback.message, edit=True)
    await callback.answer(f"Смещение: {new_offset}ч")

@dp.callback_query(F.data == "toggle_update_mode")
async def toggle_update_mode_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await database.toggle_update_status()
    await admin_panel(callback.message, edit=True)
    await callback.answer()

@dp.callback_query(F.data == "toggle_week")
async def toggle_week_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await database.toggle_week_type()
    await admin_panel(callback.message, edit=True)
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("Введите сообщение для рассылки всем пользователям:")
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.answer()

@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    user_ids = await database.get_all_users()
    count = 0
    await message.answer(f"Начинаю рассылку на {len(user_ids)} пользователей...")
    for uid in user_ids:
        try:
            await bot.send_message(uid, f"📢 *ОБЪЯВЛЕНИЕ*\n\n{message.text}", parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Рассылка завершена. Доставлено: {count}")
    await state.clear()

async def auto_weekly_task():
    new_type = await database.toggle_week_type()
    parser.update_data()
    logger.info(f"Выполнена еженедельная задача: тип недели {new_type}")

async def start_bot():
    await database.init_db()
    logger.info(f"Запуск бота. ID администратора: {ADMIN_ID}")
    await bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(text="Расписание", web_app=types.WebAppInfo(url=os.getenv("WEBAPP_URL", "http://localhost:8000"))))
    scheduler.add_job(auto_weekly_task, 'cron', day_of_week='mon', hour=0, minute=0)
    scheduler.start()
    await dp.start_polling(bot)

async def start_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    bot_task = asyncio.create_task(start_bot())
    server_task = asyncio.create_task(start_server())
    await asyncio.gather(bot_task, server_task)

if __name__ == "__main__":
    asyncio.run(main())
