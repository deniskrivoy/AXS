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
SUPPORT_USERNAME = "LZT_Support_Official"  # обновлено

# Фотографии (обновлённые ссылки)
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

def add_user(user_id, username, full_name):
    if username and username.startswith('@'):
        username = username[1:]
    db_query("INSERT OR IGNORE INTO users (user_id, username, full_name, reg_date) VALUES (?,?,?,?)",
             (user_id, username, full_name, datetime.datetime.now().isoformat()), commit=True)

def get_user(user_id):
    return db_query("SELECT * FROM users WHERE user_id=?", (user_id,), fetchone=True)

def get_user_by_username(username):
    if username and username.startswith('@'):
        username = username[1:]
    return db_query("SELECT * FROM users WHERE username=?", (username,), fetchone=True)

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
    waiting_username = State()
    waiting_wallet = State()
    waiting_screenshot1 = State()
    waiting_screenshot2 = State()
    waiting_screenshot3 = State()

class AdminStates(StatesGroup):
    waiting_reject_reason = State()
    waiting_payout_amount = State()  # новое состояние для ввода суммы при подтверждении

# ================== БОТ ==================
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

async def send_with_photo(chat_id, text, photo_url, reply_markup=None, parse_mode='HTML'):
    # Проверяем, не является ли получатель ботом
    try:
        chat = await bot.get_chat(chat_id)
        if chat.type == 'bot':
            # Не отправляем ботам, просто логируем
            logging.info(f"Попытка отправить сообщение боту {chat_id}, пропускаем.")
            return
    except Exception as e:
        logging.error(f"Ошибка проверки чата: {e}")
        # Если не можем проверить, пробуем отправить обычное сообщение
        try:
            await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass
        return

    try:
        await bot.send_photo(chat_id, photo=photo_url, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"Photo send error: {e}")
        try:
            await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e2:
            logging.error(f"Message send error: {e2}")

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
        "💳 Все выплаты производятся в <b>GRAM</b> — криптовалюте Telegram.\n\n"
        "👇 Выберите действие:"
    )
    await send_with_photo(message.chat.id, text, PHOTO_GENERAL, reply_markup=main_menu_inline(is_admin))

# ================== ОБРАБОТЧИКИ КНОПОК ==================
@dp.callback_query(F.data == "create_request")
async def create_request_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(
        "📝 <b>Создание заявки на выплату</b>\n\n"
        "Для создания заявки вам необходимо предоставить:\n"
        "1️⃣ Код сделки из бота Lolz Market OTC\n"
        "2️⃣ Ваш Telegram username (например, @username)\n"
        "3️⃣ Ваш кошелёк для получения выплаты в GRAM\n"
        "4️⃣ Доказательства (скриншоты переписки и отправки подарка)\n\n"
        "📸 <b>Внимание!</b> Без скриншотов заявка не будет рассмотрена.\n\n"
        "👉 <b>Начните с ввода кода сделки:</b>",
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
        f"• Всего заработано: {total_earned:.2f} GRAM"
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
    text = (
        f"🔧 <b>Админ-панель</b>\n\n"
        f"• Ожидают обработки: {waiting}\n"
        f"• Всего заявок: {total}\n"
    )
    await callback.message.delete()
    await send_with_photo(callback.message.chat.id, text, PHOTO_GENERAL, parse_mode='HTML')

# ================== FSM: ЗАПОЛНЕНИЕ ЗАЯВКИ ==================
@dp.message(StateFilter(PayoutStates.waiting_deal_code))
async def process_deal_code(message: types.Message, state: FSMContext):
    deal_code = message.text.strip()
    if len(deal_code) < 3:
        await message.answer("❌ Код сделки слишком короткий. Введите корректный код из бота Lolz Market OTC:", parse_mode='HTML')
        return
    await state.update_data(deal_code=deal_code)
    await message.answer("👤 Введите ваш Telegram <b>username</b> (например, @username):", parse_mode='HTML')
    await state.set_state(PayoutStates.waiting_username)

@dp.message(StateFilter(PayoutStates.waiting_username))
async def process_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if not username.startswith('@'):
        username = '@' + username
    await state.update_data(username=username)
    await message.answer("💳 Введите ваш <b>кошелёк GRAM</b> для получения выплаты:", parse_mode='HTML')
    await state.set_state(PayoutStates.waiting_wallet)

@dp.message(StateFilter(PayoutStates.waiting_wallet))
async def process_wallet(message: types.Message, state: FSMContext):
    await state.update_data(wallet=message.text.strip())
    await message.answer(
        "📸 Отправьте <b>скриншот переписки</b> с клиентом (первое фото):",
        parse_mode='HTML'
    )
    await state.set_state(PayoutStates.waiting_screenshot1)

@dp.message(StateFilter(PayoutStates.waiting_screenshot1), F.photo)
async def process_screenshot1(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(screenshot1=file_id)
    await message.answer(
        "📸 Отправьте <b>скриншот подтверждения отправки подарка</b> (второе фото):",
        parse_mode='HTML'
    )
    await state.set_state(PayoutStates.waiting_screenshot2)

@dp.message(StateFilter(PayoutStates.waiting_screenshot2), F.photo)
async def process_screenshot2(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(screenshot2=file_id)
    await message.answer(
        "📸 Отправьте <b>дополнительное фото</b> (если есть) или нажмите кнопку «Готово».",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово", callback_data="finish_screenshots")]
        ])
    )
    await state.set_state(PayoutStates.waiting_screenshot3)

@dp.message(StateFilter(PayoutStates.waiting_screenshot3), F.photo)
async def process_screenshot3(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(screenshot3=file_id)
    await finish_creation(message, state)

@dp.callback_query(F.data == "finish_screenshots")
async def finish_screenshots_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await finish_creation(callback.message, state)

async def finish_creation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    username = data['username']

    add_user(user_id, username, message.from_user.full_name)

    deal_code = data['deal_code']
    wallet = data['wallet']
    screenshot1 = data.get('screenshot1')
    screenshot2 = data.get('screenshot2')
    screenshot3 = data.get('screenshot3')

    req_id = create_request(user_id, deal_code, wallet, username)

    admin_text = (
        f"📩 <b>НОВАЯ ЗАЯВКА НА ВЫПЛАТУ</b>\n\n"
        f"👤 Воркер: {username} (ID: {user_id})\n"
        f"📋 Код сделки: <code>{deal_code}</code>\n"
        f"💳 Кошелёк GRAM: {wallet}\n"
        f"📎 Доказательства: {screenshot1 and '✅' or '❌'} {screenshot2 and '✅' or '❌'} {screenshot3 and '✅' or '❌'}\n"
        f"Статус: ⏳ Ожидает обработки"
    )

    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode='HTML', reply_markup=get_confirm_keyboard(req_id))
        if screenshot1:
            await bot.send_photo(ADMIN_ID, screenshot1, caption="📸 Скриншот 1")
        if screenshot2:
            await bot.send_photo(ADMIN_ID, screenshot2, caption="📸 Скриншот 2")
        if screenshot3:
            await bot.send_photo(ADMIN_ID, screenshot3, caption="📸 Скриншот 3")
    except Exception as e:
        logging.error(f"Не удалось отправить админу: {e}")

    await send_with_photo(
        message.chat.id,
        "✅ Ваша заявка отправлена на рассмотрение. Ожидайте подтверждения.",
        PHOTO_GENERAL,
        reply_markup=main_menu_inline(user_id==ADMIN_ID)
    )
    await state.clear()

# ================== ОБРАБОТКА ЗАЯВОК АДМИНОМ ==================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_request(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    request_id = int(callback.data.split("_")[1])
    req = get_request(request_id)
    if not req:
        await callback.message.edit_text("❌ Заявка не найдена.")
        return
    if req[5] != 'waiting':
        await callback.message.edit_text("❌ Эта заявка уже обработана.")
        return

    await callback.message.edit_text(
        "✏️ Введите <b>сумму выплаты в GRAM</b> (число):",
        parse_mode='HTML'
    )
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
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число. Например: 150.5")
        return

    data = await state.get_data()
    request_id = data['request_id']
    req = get_request(request_id)
    if not req:
        await message.answer("❌ Заявка не найдена.")
        await state.clear()
        return

    # Обновляем статус заявки
    update_request_status(request_id, 'approved')
    user_id = req[1]
    username = req[4]

    # Отправляем воркеру уведомление о выплате
    try:
        await send_with_photo(
            user_id,
            f"🎉 <b>НОВЫЙ ПРОФИТ!</b>\n\n"
            f"💰 Сумма выплаты: {amount:.2f} GRAM\n"
            f"📅 Дата: {datetime.datetime.now().strftime('%d.%m.%Y')}\n"
            f"✅ Статус: <b>Выплата выполнена!</b>\n\n"
            f"Команда <b>AXS Team</b> поздравляет вас!\n"
            f"Продолжайте в том же духе! 🚀",
            PHOTO_PROFIT,
            parse_mode='HTML'
        )
        # Обновляем статистику пользователя
        update_user_stats(user_id, amount)
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление воркеру: {e}")
        await message.answer(f"❌ Не удалось отправить уведомление воркеру: {e}")
        await state.clear()
        return

    await message.answer(f"✅ Заявка #{request_id} подтверждена. Выплата {amount:.2f} GRAM отправлена воркеру {username}.")
    await state.clear()

@dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    request_id = int(callback.data.split("_")[1])
    req = get_request(request_id)
    if not req:
        await callback.message.edit_text("❌ Заявка не найдена.")
        return
    if req[5] != 'waiting':
        await callback.message.edit_text("❌ Эта заявка уже обработана.")
        return

    await callback.message.edit_text(
        "✏️ Напишите <b>причину отказа</b> (или отправьте /cancel для отмены):",
        parse_mode='HTML'
    )
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
        await bot.send_message(
            user_id,
            f"❌ <b>Ваша заявка отклонена</b>\n\n"
            f"Причина: {reason}\n\n"
            f"Если у вас есть вопросы, обратитесь к поддержке @{SUPPORT_USERNAME}.",
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f"Не удалось уведомить воркера: {e}")

    await message.answer(f"✅ Заявка #{request_id} отклонена. Воркер уведомлён.")
    await state.clear()

# ================== СТАТИСТИКА ДЛЯ АДМИНА ==================
@dp.message(Command("stats"))
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    total_users = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    total_requests = db_query("SELECT COUNT(*) FROM payout_requests", fetchone=True)[0]
    total_paid = db_query("SELECT SUM(total_earned) FROM users", fetchone=True)[0] or 0
    text = (
        f"📊 <b>Статистика системы выплат AXS Team</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📋 Всего заявок: {total_requests}\n"
        f"💰 Выплачено: {total_paid:.2f} GRAM"
    )
    await send_with_photo(message.chat.id, text, PHOTO_GENERAL, parse_mode='HTML')

# ================== ЗАПУСК ==================
async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
