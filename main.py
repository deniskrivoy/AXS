import sqlite3
import datetime
import logging
import asyncio
import re

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================== КОНФИГ ==================
BOT_TOKEN = "8981797481:AAGJTlq2fdWyfgWtxYpkRCSwpSxie_2R2qg"
ADMIN_ID = 7652887576
SUPPORT_USERNAME = "LZT_Support_Official"

PHOTO_GENERAL = "https://i.ibb.co/bMfgcKsX/file-00000000c570820a8a6928e21d2b9d6e.png"
PHOTO_PROFIT = "https://i.ibb.co/VcM7BxP6/IMG-20260804-225836-516.jpg"

# ================== БАЗА ДАННЫХ ==================
DB_NAME = "payouts.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            wallet TEXT,
            total_earned REAL DEFAULT 0,
            total_requests INTEGER DEFAULT 0,
            reg_date TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS payout_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            deal_code TEXT,
            wallet TEXT,
            username TEXT,
            status TEXT DEFAULT 'waiting',
            admin_note TEXT,
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

def add_user(user_id, username, full_name, wallet=None):
    if username and username.startswith('@'):
        username = username[1:]
    db_query("INSERT OR IGNORE INTO users (user_id, username, full_name, wallet, reg_date) VALUES (?,?,?,?,?)",
             (user_id, username, full_name, wallet, datetime.datetime.now().isoformat()), commit=True)

def update_user_wallet(user_id, wallet):
    db_query("UPDATE users SET wallet=? WHERE user_id=?", (wallet, user_id), commit=True)

def get_user(user_id):
    return db_query("SELECT * FROM users WHERE user_id=?", (user_id,), fetchone=True)

def get_user_wallet(user_id):
    row = db_query("SELECT wallet FROM users WHERE user_id=?", (user_id,), fetchone=True)
    return row[0] if row else None

def update_user_stats(user_id, amount):
    db_query("UPDATE users SET total_earned = total_earned + ?, total_requests = total_requests + 1 WHERE user_id=?",
             (amount, user_id), commit=True)

def create_request(user_id, deal_code, wallet, username):
    if username and username.startswith('@'):
        username = username[1:]
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO payout_requests (user_id, deal_code, wallet, username, created_at) VALUES (?,?,?,?,?)",
                (user_id, deal_code, wallet, username, datetime.datetime.now().isoformat()))
    conn.commit()
    req_id = cur.lastrowid
    conn.close()
    return req_id

def get_requests(user_id):
    return db_query("SELECT id, deal_code, wallet, username, status, admin_note, created_at, processed_at FROM payout_requests WHERE user_id=? ORDER BY id DESC", (user_id,), fetchall=True)

def get_request(request_id):
    return db_query("SELECT * FROM payout_requests WHERE id=?", (request_id,), fetchone=True)

def update_request_status(request_id, status, admin_note=None):
    if admin_note:
        db_query("UPDATE payout_requests SET status=?, admin_note=?, processed_at=? WHERE id=?",
                 (status, admin_note, datetime.datetime.now().isoformat(), request_id), commit=True)
    else:
        db_query("UPDATE payout_requests SET status=?, processed_at=? WHERE id=?",
                 (status, datetime.datetime.now().isoformat(), request_id), commit=True)

def get_user_stats(user_id):
    row = db_query("SELECT total_earned, total_requests FROM users WHERE user_id=?", (user_id,), fetchone=True)
    return row if row else (0, 0)

def get_pending_requests_count():
    row = db_query("SELECT COUNT(*) FROM payout_requests WHERE status='waiting'", fetchone=True)
    return row[0] if row else 0

def get_total_requests_count():
    row = db_query("SELECT COUNT(*) FROM payout_requests", fetchone=True)
    return row[0] if row else 0

# ================== КЛАВИАТУРЫ ==================
def main_menu_inline(user_is_admin=False):
    buttons = [
        [InlineKeyboardButton(text="📝 Создать заявку", callback_data="create_request")],
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="my_requests")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")]
    ]
    if user_is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_confirm_keyboard(request_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_{request_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{request_id}")]
    ])

# ================== FSM ==================
class PayoutStates(StatesGroup):
    waiting_deal_code = State()
    waiting_wallet = State()
    waiting_screenshot1 = State()
    waiting_screenshot2 = State()
    waiting_screenshot3 = State()

class AdminStates(StatesGroup):
    waiting_reject_reason = State()
    waiting_payout_amount = State()

# ================== БОТ ==================
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

async def send_with_photo(chat_id, text, photo_url, reply_markup=None, parse_mode='HTML'):
    try:
        chat = await bot.get_chat(chat_id)
        if chat.type == 'bot':
            return
    except:
        pass
    try:
        await bot.send_photo(chat_id, photo=photo_url, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"Photo send error: {e}")
        try:
            await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except:
            pass

# ================== /start ==================
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    add_user(user_id, message.from_user.username, message.from_user.full_name)
    is_admin = (user_id == ADMIN_ID)
    text = (
        "🏛 <b>AXS Team Payouts — Система выплат</b>\n\n"
        "Добро пожаловать в систему выплат команды AXS Team!\n\n"
        "📊 Здесь вы можете:\n"
        "• Подать заявку на выплату\n"
        "• Отслеживать статус своих заявок\n"
        "• Просматривать историю выплат\n\n"
        "💳 Все выплаты производятся на <b>TON-кошелёк</b>.\n\n"
        "👇 Выберите действие:"
    )
    await send_with_photo(message.chat.id, text, PHOTO_GENERAL, reply_markup=main_menu_inline(is_admin))

# ================== ОБРАБОТЧИКИ КНОПОК ==================
@dp.callback_query(F.data == "create_request")
async def create_request_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    user_id = callback.from_user.id
    saved_wallet = get_user_wallet(user_id)
    if saved_wallet:
        await callback.message.answer(
            f"📝 <b>Создание заявки на выплату</b>\n\n"
            f"Ваш сохранённый TON-кошелёк: <code>{saved_wallet}</code>\n\n"
            f"Если хотите использовать его, просто введите код сделки.\n"
            f"Если хотите изменить кошелёк, отправьте /newwallet.\n\n"
            f"👉 <b>Введите код сделки:</b>",
            parse_mode='HTML'
        )
        await state.set_state(PayoutStates.waiting_deal_code)
        await state.update_data(wallet=saved_wallet)
    else:
        await callback.message.answer(
            "📝 <b>Создание заявки на выплату</b>\n\n"
            "1️⃣ Введите код сделки из бота Lolz Market OTC.\n"
            "2️⃣ Затем введите ваш TON-кошелёк.\n"
            "3️⃣ Отправьте скриншоты.\n\n"
            "👉 <b>Введите код сделки:</b>",
            parse_mode='HTML'
        )
        await state.set_state(PayoutStates.waiting_deal_code)

@dp.callback_query(F.data == "my_requests")
async def my_requests_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    requests = get_requests(user_id)
    if not requests:
        await callback.message.delete()
        await send_with_photo(callback.message.chat.id, "📭 У вас пока нет заявок.", PHOTO_GENERAL, reply_markup=main_menu_inline(user_id==ADMIN_ID))
        return
    text = "📋 <b>Ваши заявки:</b>\n\n"
    for req in requests:
        req_id, deal_code, wallet, username, status, note, created_at, processed_at = req
        status_emoji = "⏳" if status == 'waiting' else ("✅" if status == 'approved' else "❌")
        text += f"{status_emoji} <b>#{req_id}</b> {deal_code} — {status}\n"
        if note:
            text += f"   <i>Примечание: {note}</i>\n"
    await callback.message.delete()
    await send_with_photo(callback.message.chat.id, text, PHOTO_GENERAL, reply_markup=main_menu_inline(user_id==ADMIN_ID), parse_mode='HTML')

@dp.callback_query(F.data == "my_stats")
async def my_stats_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    total_earned, total_requests = get_user_stats(user_id)
    text = (
        f"📊 <b>Ваша статистика</b>\n\n"
        f"• Всего заявок: {total_requests}\n"
        f"• Всего заработано: {total_earned:.2f} TON"
    )
    await callback.message.delete()
    await send_with_photo(callback.message.chat.id, text, PHOTO_GENERAL, reply_markup=main_menu_inline(user_id==ADMIN_ID), parse_mode='HTML')

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: types.CallbackQuery):
    await callback.answer()
    if callback.from_user.id != ADMIN_ID:
        await callback.message.answer("❌ Доступ запрещён.")
        return
    waiting = get_pending_requests_count()
    total = get_total_requests_count()
    text = f"🔧 <b>Админ-панель</b>\n\n• Ожидают: {waiting}\n• Всего: {total}"
    await callback.message.delete()
    await send_with_photo(callback.message.chat.id, text, PHOTO_GENERAL, parse_mode='HTML')

# ================== FSM ==================
@dp.message(StateFilter(PayoutStates.waiting_deal_code))
async def process_deal_code(message: types.Message, state: FSMContext):
    deal_code = message.text.strip()
    if len(deal_code) < 3:
        await message.answer("❌ Слишком короткий код. Введите код из бота Lolz Market OTC:")
        return
    await state.update_data(deal_code=deal_code)
    # Проверяем, есть ли кошелёк в данных (если нет - запрашиваем)
    data = await state.get_data()
    if 'wallet' not in data or not data['wallet']:
        await message.answer("💳 Введите ваш <b>TON-кошелёк</b>:", parse_mode='HTML')
        await state.set_state(PayoutStates.waiting_wallet)
    else:
        await message.answer("📸 Отправьте <b>скриншот переписки</b> (1-е фото):", parse_mode='HTML')
        await state.set_state(PayoutStates.waiting_screenshot1)

@dp.message(StateFilter(PayoutStates.waiting_wallet))
async def process_wallet(message: types.Message, state: FSMContext):
    wallet = message.text.strip()
    if len(wallet) < 5:
        await message.answer("❌ Слишком короткий кошелёк. Введите корректный TON-кошелёк:")
        return
    user_id = message.from_user.id
    update_user_wallet(user_id, wallet)
    await state.update_data(wallet=wallet)
    await message.answer("📸 Отправьте <b>скриншот переписки</b> (1-е фото):", parse_mode='HTML')
    await state.set_state(PayoutStates.waiting_screenshot1)

@dp.message(StateFilter(PayoutStates.waiting_screenshot1), F.photo)
async def process_screenshot1(message: types.Message, state: FSMContext):
    await state.update_data(screenshot1=message.photo[-1].file_id)
    await message.answer("📸 Отправьте <b>скриншот отправки подарка</b> (2-е фото):", parse_mode='HTML')
    await state.set_state(PayoutStates.waiting_screenshot2)

@dp.message(StateFilter(PayoutStates.waiting_screenshot2), F.photo)
async def process_screenshot2(message: types.Message, state: FSMContext):
    await state.update_data(screenshot2=message.photo[-1].file_id)
    await message.answer("📸 Отправьте дополнительное фото (если есть) или нажмите «Готово».", parse_mode='HTML',
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text="✅ Готово", callback_data="finish_screenshots")]
                         ]))
    await state.set_state(PayoutStates.waiting_screenshot3)

@dp.message(StateFilter(PayoutStates.waiting_screenshot3), F.photo)
async def process_screenshot3(message: types.Message, state: FSMContext):
    await state.update_data(screenshot3=message.photo[-1].file_id)
    await finish_creation(message, state)

@dp.callback_query(F.data == "finish_screenshots")
async def finish_screenshots_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await finish_creation(callback.message, state)

async def finish_creation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username or "Не указан"
    if not username.startswith('@'):
        username = '@' + username

    add_user(user_id, username, message.from_user.full_name, data.get('wallet'))

    deal_code = data['deal_code']
    wallet = data['wallet']
    s1 = data.get('screenshot1')
    s2 = data.get('screenshot2')
    s3 = data.get('screenshot3')

    req_id = create_request(user_id, deal_code, wallet, username)

    admin_text = (
        f"📩 <b>НОВАЯ ЗАЯВКА НА ВЫПЛАТУ</b>\n\n"
        f"👤 Воркер: {username} (ID: {user_id})\n"
        f"📋 Код: <code>{deal_code}</code>\n"
        f"💳 TON-кошелёк: {wallet}\n"
        f"📎 Фото: {s1 and '✅' or '❌'} {s2 and '✅' or '❌'} {s3 and '✅' or '❌'}"
    )

    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode='HTML', reply_markup=get_confirm_keyboard(req_id))
        if s1: await bot.send_photo(ADMIN_ID, s1, caption="📸 Скриншот 1")
        if s2: await bot.send_photo(ADMIN_ID, s2, caption="📸 Скриншот 2")
        if s3: await bot.send_photo(ADMIN_ID, s3, caption="📸 Скриншот 3")
    except Exception as e:
        logging.error(f"Ошибка отправки админу: {e}")

    await send_with_photo(message.chat.id, "✅ Заявка отправлена. Ожидайте подтверждения.", PHOTO_GENERAL,
                          reply_markup=main_menu_inline(user_id==ADMIN_ID))
    await state.clear()

# ================== АДМИН: ПОДТВЕРЖДЕНИЕ ==================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_request(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    request_id = int(callback.data.split("_")[1])
    req = get_request(request_id)
    if not req or req[5] != 'waiting':
        await callback.message.edit_text("❌ Заявка не найдена или уже обработана.")
        return
    await callback.message.edit_text("✏️ Введите <b>сумму выплаты в TON</b> (число):", parse_mode='HTML')
    await state.set_state(AdminStates.waiting_payout_amount)
    await state.update_data(request_id=request_id)

@dp.message(StateFilter(AdminStates.waiting_payout_amount))
async def process_payout_amount(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await state.clear()
        await message.answer("Отмена.")
        return
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0: raise ValueError
    except:
        await message.answer("❌ Введите положительное число.")
        return

    data = await state.get_data()
    request_id = data['request_id']
    req = get_request(request_id)
    if not req:
        await message.answer("❌ Заявка не найдена.")
        await state.clear()
        return

    update_request_status(request_id, 'approved')
    user_id = req[1]
    username = req[4]

    try:
        await send_with_photo(
            user_id,
            f"🎉 <b>НОВЫЙ ПРОФИТ!</b>\n\n"
            f"💰 Сумма: {amount:.2f} TON\n"
            f"📅 Дата: {datetime.datetime.now().strftime('%d.%m.%Y')}\n"
            f"✅ Статус: <b>Выплата выполнена!</b>\n\n"
            f"Команда <b>AXS Team</b> поздравляет вас!\n"
            f"Продолжайте в том же духе! 🚀",
            PHOTO_PROFIT,
            parse_mode='HTML'
        )
        update_user_stats(user_id, amount)
    except Exception as e:
        logging.error(f"Ошибка отправки воркеру: {e}")
        await message.answer(f"❌ Не удалось отправить уведомление: {e}")
        await state.clear()
        return

    await message.answer(f"✅ Заявка #{request_id} подтверждена. Выплата {amount:.2f} TON отправлена {username}.")
    await state.clear()

# ================== АДМИН: ОТКЛОНЕНИЕ ==================
@dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    request_id = int(callback.data.split("_")[1])
    req = get_request(request_id)
    if not req or req[5] != 'waiting':
        await callback.message.edit_text("❌ Заявка не найдена или уже обработана.")
        return
    await callback.message.edit_text("✏️ Напишите <b>причину отказа</b> (или /cancel):", parse_mode='HTML')
    await state.set_state(AdminStates.waiting_reject_reason)
    await state.update_data(request_id=request_id)

@dp.message(StateFilter(AdminStates.waiting_reject_reason))
async def process_reject_reason(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await state.clear()
        await message.answer("Отмена.")
        return
    reason = message.text
    data = await state.get_data()
    request_id = data['request_id']
    update_request_status(request_id, 'rejected', reason)
    req = get_request(request_id)
    user_id = req[1]
    try:
        await bot.send_message(user_id, f"❌ <b>Заявка отклонена</b>\n\nПричина: {reason}\n\nПоддержка: @{SUPPORT_USERNAME}", parse_mode='HTML')
    except:
        pass
    await message.answer(f"✅ Заявка #{request_id} отклонена.")

# ================== КОМАНДА ДЛЯ СМЕНЫ КОШЕЛЬКА ==================
@dp.message(Command("newwallet"))
async def new_wallet_command(message: types.Message, state: FSMContext):
    await message.answer("💳 Введите ваш новый <b>TON-кошелёк</b>:", parse_mode='HTML')
    await state.set_state(PayoutStates.waiting_wallet)

# ================== СТАТИСТИКА ДЛЯ АДМИНА ==================
@dp.message(Command("stats"))
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    total_users = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    total_requests = db_query("SELECT COUNT(*) FROM payout_requests", fetchone=True)[0]
    total_paid = db_query("SELECT SUM(total_earned) FROM users", fetchone=True)[0] or 0
    text = f"📊 <b>Статистика</b>\n\n👥 Пользователей: {total_users}\n📋 Заявок: {total_requests}\n💰 Выплачено: {total_paid:.2f} TON"
    await send_with_photo(message.chat.id, text, PHOTO_GENERAL, parse_mode='HTML')

# ================== ЗАПУСК ==================
async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
