import asyncio
import os
import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database
from parser import parser
from bot_instance import bot # Используем единый экземпляр бота
import uvicorn
from webapp.app import app
from fastapi import Request

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"[WEB] Запрос: {request.method} {request.url}")
    response = await call_next(request)
    return response

load_dotenv()

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
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    return msk + timedelta(hours=offset)

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

@dp.message(Command("chat_id"))
async def cmd_chat_id(message: types.Message):
    await message.answer(f"ID этого чата: {message.chat.id}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await track_activity(message.from_user.id)
    user_data = await database.get_user_data(message.from_user.id)
    if user_data:
        course, group, subgroup = user_data[0], user_data[1], user_data[2]
        await message.answer(f"Привет! Ты уже зарегистрирован.\n🎓 {course}, {group}, подгруппа {subgroup}", reply_markup=get_main_keyboard())
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
    data = await state.get_data()
    course = data.get('course', '')
    await state.update_data(group=group)
    subgroups = parser.get_subgroups(course, group)
    builder = InlineKeyboardBuilder()
    for sg in subgroups:
        builder.button(text=f"{sg} подгруппа", callback_data=f"subgroup_{sg}")
    builder.adjust(1)
    await callback.message.edit_text(f"Группа: {group}. Выбери подгруппу:", reply_markup=builder.as_markup())
    await state.set_state(Registration.choosing_subgroup)

@dp.callback_query(Registration.choosing_subgroup, F.data.startswith("subgroup_"))
async def process_subgroup(callback: types.CallbackQuery, state: FSMContext):
    subgroup = callback.data.split("_")[1]
    data = await state.get_data()
    await database.save_user_data(callback.from_user.id, data['course'], data['group'], subgroup)
    await state.clear()
    await callback.message.answer(f"Регистрация завершена!\n🎓 {data['course']}, {data['group']}, подгруппа {subgroup}", reply_markup=get_main_keyboard())
    await callback.answer()

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

async def get_schedule_text(user_id, target_date: datetime, day_name: str = None):
    if await database.get_update_status():
        return "⚠️ <b>ВНИМАНИЕ</b>\n\nВ данный момент расписание обновляется. Пожалуйста, зайдите позже."
    user_data = await database.get_user_data(user_id)
    if not user_data: return "Сначала пройди регистрацию /start"
    course, group, subgroup, mode, show_timer, timer_mode, show_break = user_data
    week_type = await get_display_week_type(target_date)
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    if not day_name:
        day_name = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][target_date.weekday()]
    if day_name == "Воскресенье":
        text = f"📅 <b>{day_name}</b> ({week_name})\n"
        if mode == "po***": text += "🎉 Похуй, домой"
        elif mode == "пивко": text += "🎉 По пивку, чилл"
        else: text += "🎉 Пар нет, отдыхай!"
        return text
    schedule = parser.get_schedule(course, group, subgroup, week_type)
    day_schedule = schedule.get(day_name) if isinstance(schedule, dict) else None
    text = f"📅 <b>{day_name}</b> ({week_name})\n───────────────\n\n"
    if not day_schedule:
        if mode == "po***": text += "🎉 Похуй, домой"
        elif mode == "пивко": text += "🎉 По пивку, чилл"
        else: text += "🎉 Пар нет, отдыхай!"
    else:
        day_schedule = apply_mode_transformations(day_schedule, mode)
        clean_schedule = []
        for s in day_schedule:
            s = s.replace('*', '').replace('_', '')
            if ' - ' in s or ':' in s:
                parts = s.split(':', 1)
                if len(parts) > 1: clean_schedule.append(f"<b>{parts[0]}</b>:{parts[1]}")
                else: clean_schedule.append(s)
            else: clean_schedule.append(s)
        text += "\n\n".join(clean_schedule)
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
    now = await get_now(); week_type = await get_display_week_type(now)
    week_label = "Числитель" if week_type == 0 else "Знаменатель"
    day_name_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][now.weekday()]
    builder = InlineKeyboardBuilder()
    builder.button(text=f"✨ СЕЙЧАС ({day_name_short}, {week_label})", callback_data=f"roomdw_curr")
    days_list = [("Понедельник", "Пн"), ("Вторник", "Вт"), ("Среда", "Ср"), ("Четверг", "Чт"), ("Пятница", "Пт"), ("Суббота", "Сб")]
    for full_n, short_n in days_list:
        builder.button(text=f"{short_n} [Чи]", callback_data=f"roomdw_{full_n}_0")
        builder.button(text=f"{short_n} [Зн]", callback_data=f"roomdw_{full_n}_1")
    builder.adjust(1, 2)
    await callback.message.edit_text("📅 <b>Выбор дня и недели</b>\nУкажите, на когда ищем свободные аудитории:", reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(FreeRoomSearch.choosing_day_week)
    await callback.answer()

@dp.callback_query(FreeRoomSearch.choosing_day_week, F.data.startswith("roomdw_"))
async def free_rooms_slot_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "roomdw_curr":
        now = await get_now(); week_type = await get_display_week_type(now)
        day_name = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][now.weekday()]
    else:
        parts = callback.data.split("_"); day_name = parts[1]; week_type = int(parts[2])
    await state.update_data(search_day=day_name, search_week=week_type)
    builder = InlineKeyboardBuilder()
    for slot in parser.TIME_SLOTS: builder.button(text=slot, callback_data=f"roomslot_{slot}")
    builder.adjust(2)
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    await callback.message.edit_text(f"Ищем на: <b>{day_name}</b> ({week_name})\nТеперь выберите пару по времени:", reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(FreeRoomSearch.choosing_slot)
    await callback.answer()

@dp.callback_query(FreeRoomSearch.choosing_slot, F.data.startswith("roomslot_"))
async def process_free_rooms(callback: types.CallbackQuery, state: FSMContext):
    slot = callback.data.split("_")[1]; data = await state.get_data()
    day_name = data.get('search_day'); week_type = data.get('search_week')
    if day_name == "Воскресенье":
        await callback.message.answer("Сегодня воскресенье, все аудитории свободны!"); await state.clear(); return
    rooms = parser.get_free_classrooms(day_name, slot, week_type)
    week_name = "Числитель" if week_type == 0 else "Знаменатель"
    text = f"🚪 <b>Свободные аудитории</b>\n📅 {day_name} ({week_name})\n⏰ Время: {slot}\n───────────────\n\n"
    if not rooms['main'] and not rooms['p']: text += "Все аудитории заняты! 😱"
    else:
        if rooms['main']: text += "<b>Главный корпус / 2 корпус:</b>\n" + ", ".join(rooms['main']) + "\n\n"
        if rooms['p']: text += "<b>Пристройка (П):</b>\n" + ", ".join(rooms['p']) + "\n"
    await callback.message.answer(text, parse_mode="HTML"); await state.clear(); await callback.answer()

@dp.message(TeacherSearch.waiting_for_name)
async def process_teacher_search(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3: await message.answer("Пожалуйста, введите хотя бы 3 буквы для поиска."); return
    results = parser.get_teacher_schedule(name)
    if not results: await message.answer(f"Преподаватель '{name}' не найден.")
    else:
        text = f"🔍 <b>Результаты поиска: {name}</b>\n───────────────\n\n"
        for res in results: text += f"📅 <b>{res['day']}</b> | {res['time']}\n🏷 [{res['week_type']}]\n🎓 {res['course']}, {res['group']}\n📖 {res['subject']}\n\n"
        if len(text) > 4000: await message.answer(text[:4000], parse_mode="HTML"); await message.answer(text[4000:], parse_mode="HTML")
        else: await message.answer(text, parse_mode="HTML")
    await state.clear()

@dp.message(F.text.regexp(r"(📅 (Понедельник|Вторник|Среда|Четверг|Пятница|Суббота))"))
async def show_day_schedule(message: types.Message):
    await track_activity(message.from_user.id); day = message.text.split(" ")[1]
    now = await get_now(); text = await get_schedule_text(message.from_user.id, now, day)
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "📌 На сегодня")
async def show_today(message: types.Message):
    await track_activity(message.from_user.id); now = await get_now()
    text = await get_schedule_text(message.from_user.id, now)
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "➡️ На завтра")
async def show_tomorrow(message: types.Message):
    await track_activity(message.from_user.id); now = await get_now(); tomorrow = now + timedelta(days=1)
    text = await get_schedule_text(message.from_user.id, tomorrow)
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🗓 Расписание на неделю")
async def show_week_schedule(message: types.Message):
    await track_activity(message.from_user.id); user_data = await database.get_user_data(message.from_user.id)
    if not user_data: await message.answer("Сначала пройди регистрацию /start"); return
    now = await get_now(); display_date = now + timedelta(days=1) if now.weekday() == 6 else now
    week_type = await get_display_week_type(display_date); week_name = "Числитель" if week_type == 0 else "Знаменатель"
    course, group, subgroup = user_data[0], user_data[1], user_data[2]
    mode = user_data[3]
    schedule = parser.get_schedule(course, group, subgroup, week_type)
    header = f"🗓 <b>РАСПИСАНИЕ НА НЕДЕЛЮ</b> ({week_name})\n🎓 {course}, {group}, подгруппа {subgroup}\n════════════════════\n\n"
    await message.answer(header, parse_mode="HTML")
    for day in ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]:
        day_sch = schedule.get(day); text = f"🔸 <b>{day}</b>\n"
        if not day_sch: text += "— Похуй, домой\n\n" if mode == "po***" else ("— По пивку, чилл\n\n" if mode == "пивко" else "— Пар нет\n\n")
        else:
            day_sch = apply_mode_transformations(day_sch, mode)
            clean_day = []
            for s in day_sch:
                s = s.replace('*', '').replace('_', '')
                if ':' in s:
                    parts = s.split(':', 1)
                    clean_day.append(f"<b>{parts[0]}</b>:{parts[1]}")
                else: clean_day.append(s)
            text += "\n".join(clean_day) + "\n\n"
        await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "👤 Мой профиль")
async def show_profile(message: types.Message):
    await track_activity(message.from_user.id); user_data = await database.get_user_data(message.from_user.id)
    if user_data:
        course, group, subgroup = user_data[0], user_data[1], user_data[2]
        text = f"👤 <b>Мой профиль</b>\n\nКурс: {course}\n{group}\nПодгруппа: {subgroup}"
        builder = InlineKeyboardBuilder(); builder.button(text="Изменить данные", callback_data="re_register")
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else: await message.answer("Ты еще не зарегистрирован.")

@dp.callback_query(F.data == "re_register")
async def re_register(callback: types.CallbackQuery, state: FSMContext):
    await track_activity(callback.from_user.id); await start_registration(callback.message, state); await callback.answer()

@dp.message(F.text == "⚙️ Режим")
@dp.message(Command("mode"))
async def show_mode_menu(message: types.Message):
    await track_activity(message.from_user.id); current_mode = await database.get_user_mode(message.from_user.id)
    builder = InlineKeyboardBuilder()
    for mid, mname in [("обычный", "обычный"), ("po***", "po***"), ("пивко", "пивко")]:
        status = " ✅" if current_mode == mid else ""
        builder.button(text=f"{mname}{status}", callback_data=f"set_mode_{mid}")
    builder.adjust(1); await message.answer(f"Выберите режим (текущий: {current_mode}):", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("set_mode_"))
async def set_mode_cb(callback: types.CallbackQuery):
    await track_activity(callback.from_user.id); mode = callback.data.split("_")[2]
    await database.set_user_mode(callback.from_user.id, mode)
    await callback.message.edit_text(f"✅ Режим изменен на: <b>{mode}</b>", parse_mode="HTML"); await callback.answer()

@dp.message(F.text == "🆘 Неправильное расписание?")
async def report_start(message: types.Message, state: FSMContext):
    await track_activity(message.from_user.id); await message.answer("Опишите проблему. Я передам это администратору."); await state.set_state(ReportState.waiting_for_report)

@dp.message(ReportState.waiting_for_report)
async def process_report(message: types.Message, state: FSMContext):
    await track_activity(message.from_user.id); user_info = f"ID: {message.from_user.id}\nИмя: {message.from_user.full_name}"
    if message.from_user.username: user_info += f" (@{message.from_user.username})"
    await database.add_report(message.from_user.id, message.from_user.full_name, message.text)
    # Попытка отправить в группу, иначе в личку админу
    try:
        await bot.send_message(REPORTS_CHAT_ID, f"🔔 <b>НОВАЯ ЖАЛОБА</b>\n\n{user_info}\n\nТекст:\n{message.text}", parse_mode="HTML")
    except:
        await bot.send_message(ADMIN_ID, f"🔔 <b>НОВАЯ ЖАЛОБА (в личку)</b>\n\n{user_info}\n\nТекст:\n{message.text}", parse_mode="HTML")
    await message.answer("✅ Ваше сообщение отправлено администратору. Спасибо!"); await state.clear()

@dp.message(F.reply_to_message, (F.from_user.id == ADMIN_ID) | (F.chat.id == REPORTS_CHAT_ID))
async def handle_admin_reply(message: types.Message):
    rt = message.reply_to_message.text
    if rt and "ID: " in rt:
        try:
            tid = int(rt.split("ID: ")[1].split("\n")[0])
            await bot.send_message(tid, f"📩 <b>Ответ от администратора:</b>\n\n{message.text}", parse_mode="HTML")
            await message.answer("✅ Ответ отправлен.")
        except Exception as e: await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("admin"))
async def admin_panel(message: types.Message, edit: bool = False):
    if message.from_user.id != ADMIN_ID: return
    stats = await database.get_stats(); week_type = await database.get_week_type()
    week_name = "Числитель" if week_type == 0 else "Знаменатель"; is_updating = await database.get_update_status()
    offset = await database.get_timezone_offset(); ust = "🔴 Выключить режим обновления" if is_updating else "🟢 Включить режим обновления"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Сменить тип недели", callback_data="toggle_week")
    builder.button(text=ust, callback_data="toggle_update_mode")
    builder.button(text="📥 Обновить данные", callback_data="admin_update_data")
    builder.button(text="📢 Рассылка всем", callback_data="admin_broadcast")
    builder.button(text=f"⏰ Смещение: {'+' if offset >= 0 else ''}{offset}ч", callback_data="none")
    builder.button(text="➖ 1 час", callback_data="offset_minus"); builder.button(text="➕ 1 час", callback_data="offset_plus")
    builder.adjust(1, 1, 1, 1, 1, 2); now = await get_now()
    offset_str = f"+{offset}" if offset > 0 else str(offset)
    status_msg = f"⚙️ <b>Админ-панель</b>\n\n📊 <b>Статистика:</b>\n— Всего: {stats['total']}\n— Активны сегодня: {stats['daily']}\n\n📅 Неделя: {week_name}\n🕒 Время бота (МСК {offset_str}ч): <b>{now.strftime('%H:%M')}</b>\n"
    status_msg += "⚠️ <b>РЕЖИМ ОБНОВЛЕНИЯ ВКЛЮЧЕН</b>" if is_updating else "✅ Расписание доступно"
    if edit:
        try: await message.edit_text(status_msg, reply_markup=builder.as_markup(), parse_mode="HTML")
        except: pass
    else: await message.answer(status_msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("offset_"))
async def offset_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    curr = await database.get_timezone_offset(); new_o = curr + (1 if "plus" in callback.data else -1)
    await database.set_timezone_offset(new_o); await admin_panel(callback.message, edit=True); await callback.answer(f"Смещение: {new_o}ч")

@dp.callback_query(F.data == "toggle_update_mode")
async def toggle_update_mode_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    s = await database.toggle_update_status(); await admin_panel(callback.message, edit=True); await callback.answer(f"Обновление {'вкл' if s else 'выкл'}")

@dp.callback_query(F.data == "toggle_week")
async def toggle_week_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await database.toggle_week_type(); await admin_panel(callback.message, edit=True); await callback.answer("Тип недели изменен")

@dp.callback_query(F.data == "admin_update_data")
async def admin_update_data_cb(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await callback.answer("⏳ Начинаю парсинг Excel...", show_alert=False)
    try:
        if parser.update_data(): await callback.answer("✅ Успешно обновлено!", show_alert=True)
        else: await callback.answer("❌ Ошибка парсинга.", show_alert=True)
    except Exception as e: await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    await admin_panel(callback.message, edit=True)

@dp.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("Введите сообщение для рассылки:"); await state.set_state(BroadcastState.waiting_for_message); await callback.answer()

@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    uids = await database.get_all_users(); count = 0
    await message.answer(f"Рассылка на {len(uids)} чел...");
    for uid in uids:
        try: await bot.send_message(uid, f"📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n{message.text}", parse_mode="HTML"); count += 1; await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ Готово. Доставлено: {count}"); await state.clear()

async def auto_weekly_task():
    nt = await database.toggle_week_type(); parser.update_data(); logger.info(f"Задача выполнена: тип {nt}")

async def start_bot():
    await database.init_db(); logger.info(f"Запуск. Admin: {ADMIN_ID}")
    await bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(text="Расписание", web_app=types.WebAppInfo(url=os.getenv("WEBAPP_URL", "http://localhost:8000"))))
    scheduler.add_job(auto_weekly_task, 'cron', day_of_week='mon', hour=0, minute=0); scheduler.start(); await dp.start_polling(bot)

async def start_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info"); server = uvicorn.Server(config); await server.serve()

async def main():
    bot_task = asyncio.create_task(start_bot()); server_task = asyncio.create_task(start_server()); await asyncio.gather(bot_task, server_task)

if __name__ == "__main__": asyncio.run(main())
