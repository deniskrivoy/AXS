import sqlite3
import datetime
import json
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ========== КОНФИГ (ВСЁ ЗАПОЛНЕНО) ==========
BOT_TOKEN = "8981797481:AAGJTlq2fdWyfgWtxYpkRCSwpSxie_2R2qg"
ADMIN_ID = 7652887576
CHAT_LINK = "https://t.me/+l8C0Mykpz643NTQx"
GREETING_PHOTO_URL = "https://i.ibb.co/ymMnPMGB/file-00000000916482438412bd60b8de6cea.png"
PHOTO_PROFIT = "https://i.ibb.co/VcM7BxP6/IMG-20260804-225836-516.jpg"  # картинка для профита
# ============================================

DB_NAME = "workers_applications.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT,
            full_name TEXT,
            answers TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(query, params)
    if commit:
        conn.commit()
        result = None
    elif fetchone:
        result = cur.fetchone()
    elif fetchall:
        result = cur.fetchall()
    else:
        result = None
    conn.close()
    return result

def add_application(user_id, username, full_name, answers):
    db_query(
        "INSERT INTO applications (user_id, username, full_name, answers, created_at, status) VALUES (?,?,?,?,?,?)",
        (user_id, username, full_name, json.dumps(answers, ensure_ascii=False), datetime.datetime.now().isoformat(), 'pending'),
        commit=True
    )

def get_application(user_id):
    return db_query("SELECT * FROM applications WHERE user_id=?", (user_id,), fetchone=True)

def update_status(user_id, status):
    db_query("UPDATE applications SET status=?, processed_at=? WHERE user_id=?", (status, datetime.datetime.now().isoformat(), user_id), commit=True)

logging.basicConfig(level=logging.INFO)

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

class ApplicationForm(StatesGroup):
    waiting_name = State()
    waiting_experience = State()
    waiting_hours = State()
    waiting_motivation = State()
    waiting_vpn = State()
    waiting_rules = State()

# ========== КНОПКИ (ЗЕЛЁНЫЕ) ==========
def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подать заявку", callback_data="apply", style="success")]
    ])

def get_experience_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Нет опыта", callback_data="exp_0", style="success")],
        [InlineKeyboardButton(text="До 1 года", callback_data="exp_1", style="success")],
        [InlineKeyboardButton(text="1-3 года", callback_data="exp_3", style="success")],
        [InlineKeyboardButton(text="Более 3 лет", callback_data="exp_5", style="success")],
    ])

def get_yes_no_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="yes", style="success"),
         InlineKeyboardButton(text="Нет", callback_data="no", style="success")]
    ])

def get_admin_keyboard(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_{user_id}", style="success"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}", style="danger")]
    ])

# ========== ФУНКЦИЯ ОТПРАВКИ С ФОТО ==========
async def send_with_photo(chat_id, text, photo_url, reply_markup=None, parse_mode='HTML'):
    try:
        await bot.send_photo(chat_id, photo=photo_url, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"Photo send error: {e}")
        await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

# ========== /start ==========
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    app = get_application(user_id)
    if app and app[5] == 'pending':
        await message.answer("⏳ Ваша заявка уже рассматривается. Ожидайте решения.")
        return
    elif app and app[5] == 'accepted':
        await message.answer("✅ Вы уже приняты в команду! Добро пожаловать.")
        return
    elif app and app[5] == 'rejected':
        await message.answer("❌ Ваша предыдущая заявка была отклонена. Вы можете подать новую через 7 дней.")
        return
    caption_text = (
        "🏛 <b>AXS Team — Набор в команду</b>\n\n"
        "Приветствуем! Мы ищем толковых ребят для работы в сфере NFT-скама.\n"
        "Заполни анкету и стань частью нашей команды.\n\n"
        "👇 Нажми кнопку ниже, чтобы начать."
    )
    await bot.send_photo(
        chat_id=message.chat.id,
        photo=GREETING_PHOTO_URL,
        caption=caption_text,
        reply_markup=get_start_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "apply")
async def apply_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    app = get_application(user_id)
    if app:
        if app[5] == 'pending':
            await callback.message.edit_text("⏳ Ваша заявка уже рассматривается. Ожидайте решения.")
            return
        elif app[5] == 'accepted':
            await callback.message.edit_text("✅ Вы уже приняты в команду! Добро пожаловать.")
            return
        elif app[5] == 'rejected':
            await callback.message.edit_text("❌ Ваша предыдущая заявка была отклонена. Вы можете подать новую через 7 дней.")
            return
    await callback.message.delete()
    await callback.message.answer("📝 Представьтесь (имя или ник):")
    await state.set_state(ApplicationForm.waiting_name)

@dp.message(StateFilter(ApplicationForm.waiting_name))
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(
        "👨‍💻 Какой у вас опыт в скаме по NFT-подаркам?",
        reply_markup=get_experience_keyboard()
    )
    await state.set_state(ApplicationForm.waiting_experience)

@dp.callback_query(StateFilter(ApplicationForm.waiting_experience), F.data.startswith("exp_"))
async def process_experience(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    exp_map = {
        "exp_0": "Нет опыта",
        "exp_1": "До 1 года",
        "exp_3": "1-3 года",
        "exp_5": "Более 3 лет"
    }
    await state.update_data(experience=exp_map.get(callback.data, "Не указано"))
    await callback.message.delete()
    await callback.message.answer("⏰ Сколько часов в день вы готовы уделять работе? (введите число)")
    await state.set_state(ApplicationForm.waiting_hours)

@dp.message(StateFilter(ApplicationForm.waiting_hours))
async def process_hours(message: types.Message, state: FSMContext):
    try:
        hours = int(message.text)
        if hours <= 0:
            raise ValueError
    except:
        await message.answer("❌ Пожалуйста, введите положительное число. Например: 4")
        return
    await state.update_data(hours=hours)
    await message.answer("💬 Почему вы хотите присоединиться к AXS Team? (напишите кратко)")
    await state.set_state(ApplicationForm.waiting_motivation)

@dp.message(StateFilter(ApplicationForm.waiting_motivation))
async def process_motivation(message: types.Message, state: FSMContext):
    await state.update_data(motivation=message.text)
    await message.answer(
        "🛡️ У вас есть доступ к стабильному VPN?",
        reply_markup=get_yes_no_keyboard()
    )
    await state.set_state(ApplicationForm.waiting_vpn)

@dp.callback_query(StateFilter(ApplicationForm.waiting_vpn), F.data.in_({"yes", "no"}))
async def process_vpn(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(vpn="Да" if callback.data == "yes" else "Нет")
    await callback.message.delete()
    await callback.message.answer(
        "📜 Готовы ли вы соблюдать правила нашей команды? (анонимность, конфиденциальность)",
        reply_markup=get_yes_no_keyboard()
    )
    await state.set_state(ApplicationForm.waiting_rules)

@dp.callback_query(StateFilter(ApplicationForm.waiting_rules), F.data.in_({"yes", "no"}))
async def process_rules(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    rules = "Да" if callback.data == "yes" else "Нет"
    if rules == "Нет":
        await callback.message.delete()
        await callback.message.answer("❌ К сожалению, без соблюдения правил мы не можем принять вас. Удачи!")
        await state.clear()
        return
    await state.update_data(rules=rules)
    data = await state.get_data()
    answers = {
        "name": data.get("name"),
        "experience": data.get("experience"),
        "hours": data.get("hours"),
        "motivation": data.get("motivation"),
        "vpn": data.get("vpn"),
        "rules": data.get("rules")
    }
    user_id = callback.from_user.id
    username = callback.from_user.username or "Нет username"
    full_name = callback.from_user.full_name
    add_application(user_id, username, full_name, answers)
    await callback.message.delete()
    admin_text = (
        f"📩 <b>НОВАЯ ЗАЯВКА В КОМАНДУ!</b>\n\n"
        f"👤 <b>Имя:</b> {answers['name']}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"👤 <b>Username:</b> @{username}\n"
        f"📋 <b>Опыт в скаме:</b> {answers['experience']}\n"
        f"⏰ <b>Часов в день:</b> {answers['hours']}\n"
        f"💬 <b>Мотивация:</b> {answers['motivation']}\n"
        f"🛡 <b>VPN:</b> {answers['vpn']}\n"
        f"📜 <b>Согласен с правилами:</b> {answers['rules']}\n"
        f"📅 <b>Дата:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    await bot.send_message(
        ADMIN_ID,
        admin_text,
        reply_markup=get_admin_keyboard(user_id),
        parse_mode="HTML"
    )
    await callback.message.answer("✅ Ваша заявка отправлена на рассмотрение. Ожидайте ответа в ближайшее время.")
    await state.clear()

# ========== ПРИНЯТИЕ ЗАЯВКИ ==========
@dp.callback_query(F.data.startswith("accept_"))
async def accept_application(callback: CallbackQuery):
    await callback.answer()
    user_id = int(callback.data.split("_")[1])
    app = get_application(user_id)
    if not app:
        await callback.message.edit_text("❌ Заявка не найдена.")
        return
    if app[5] != 'pending':
        await callback.message.edit_text(f"❌ Заявка уже обработана (статус: {app[5]})")
        return
    update_status(user_id, 'accepted')
    
    # ОТПРАВЛЯЕМ КРАСИВОЕ СООБЩЕНИЕ С ФОТО "НОВЫЙ ПРОФИТ!"
    try:
        await send_with_photo(
            user_id,
            f"🎉 <b>НОВЫЙ ПРОФИТ!</b>\n\n"
            f"💰 <b>Вы приняты в команду AXS Team!</b>\n"
            f"📅 <b>Дата:</b> {datetime.datetime.now().strftime('%d.%m.%Y')}\n"
            f"✅ <b>Статус:</b> <i>Добро пожаловать!</i>\n\n"
            f"Команда <b>AXS Team</b> поздравляет вас!\n"
            f"Переходите в общий чат и начинайте работать! 🚀",
            PHOTO_PROFIT,
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"Не удалось отправить профит: {e}")
        await bot.send_message(
            user_id,
            f"🎉 <b>Поздравляем!</b>\n\n"
            f"Ваша заявка принята! Добро пожаловать в команду AXS Team.\n"
            f"Присоединяйтесь к общему чату: {CHAT_LINK}\n\n"
            f"Будем на связи!",
            parse_mode="HTML"
        )
    
    await callback.message.edit_text(f"✅ Заявка от {app[2]} принята. Воркер уведомлён с профитом!")

# ========== ОТКЛОНЕНИЕ ЗАЯВКИ ==========
@dp.callback_query(F.data.startswith("reject_"))
async def reject_application(callback: CallbackQuery):
    await callback.answer()
    user_id = int(callback.data.split("_")[1])
    app = get_application(user_id)
    if not app:
        await callback.message.edit_text("❌ Заявка не найдена.")
        return
    if app[5] != 'pending':
        await callback.message.edit_text(f"❌ Заявка уже обработана (статус: {app[5]})")
        return
    update_status(user_id, 'rejected')
    await bot.send_message(
        user_id,
        "😔 <b>Спасибо за вашу заявку!</b>\n\n"
        "К сожалению, мы не можем принять вас в команду сейчас.\n"
        "Возможно, мы свяжемся с вами позже.\n\n"
        "Удачи!",
        parse_mode="HTML"
    )
    await callback.message.edit_text(f"❌ Заявка от {app[2]} отклонена. Воркер уведомлён.")

# ================== ЗАПУСК ==================
async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
