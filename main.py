import requests
import json
import time
import random
import string
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import hashlib
import hmac
from functools import wraps

# ============================================================================
# КОНФИГУРАЦИЯ БОТА
# ============================================================================

BOT_TOKEN = "8497365873:AAEbquvUEc79JmTtuJHqHGu_Rm0Uzi5A1-s"
ADMIN_ID = 7694543415
CHANNEL_ID = -1001234567890  # Будет заменен на правильный ID канала
CHANNEL_USERNAME = "DexterLogovo"
BOT_NAME = "DexterFreeVpn"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Константы времени
FREE_VPN_COOLDOWN_DAYS = 21  # 3 недели
FREE_VPN_COOLDOWN_REFERRAL = 20  # На 1 день меньше (3 недели - 1 день)
REFERRAL_NOTIFICATION_ENABLED = True

# Тарифы
TARIFFS = {
    "month": {"price": 50, "duration_days": 30, "name": "На месяц"},
    "year": {"price": 150, "duration_days": 365, "name": "На год"},
    "5years": {"price": 265, "duration_days": 1825, "name": "На 5 лет"}
}

# Настройки VPN раздачи
VPN_PER_DAY = [1, 2]  # 1-2 впн в день

# ============================================================================
# БАЗА ДАННЫХ
# ============================================================================

class Database:
    def __init__(self, db_name="vpn_bot.db"):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                referrer_id INTEGER,
                referral_code TEXT UNIQUE,
                last_free_vpn_date TIMESTAMP,
                free_vpn_reset_count INTEGER DEFAULT 0,
                premium_until TIMESTAMP,
                is_subscribed_to_channel BOOLEAN DEFAULT 0,
                notifications_enabled BOOLEAN DEFAULT 1,
                is_online BOOLEAN DEFAULT 0,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица VPN
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vpns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vpn_address TEXT NOT NULL,
                vpn_key TEXT NOT NULL,
                vpn_config TEXT,
                is_active BOOLEAN DEFAULT 1,
                given_to_users TEXT DEFAULT '[]',
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expiry_date TIMESTAMP
            )
        ''')

        # Таблица промокодов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                reward_type TEXT DEFAULT 'reset_cooldown',
                usage_limit INTEGER,
                usage_count INTEGER DEFAULT 0,
                created_by INTEGER,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                user_id_used INTEGER UNIQUE
            )
        ''')

        # Таблица покупок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff TEXT NOT NULL,
                price REAL NOT NULL,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                premium_until TIMESTAMP,
                transaction_id TEXT UNIQUE,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        # Таблица рефералов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL,
                referred_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                bonus_applied BOOLEAN DEFAULT 0,
                FOREIGN KEY(referrer_id) REFERENCES users(user_id),
                FOREIGN KEY(referred_user_id) REFERENCES users(user_id)
            )
        ''')

        # Таблица логов администратора
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица капчи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS captcha_sessions (
                session_id TEXT UNIQUE PRIMARY KEY,
                user_id INTEGER,
                referrer_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                solved BOOLEAN DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()

    def execute(self, query, params=()):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        conn.close()

    def fetch_one(self, query, params=()):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchone()
        conn.close()
        return result

    def fetch_all(self, query, params=()):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchall()
        conn.close()
        return result

# Инициализация БД
db = Database()

# ============================================================================
# TELEGRAM API ФУНКЦИИ
# ============================================================================

class TelegramAPI:
    @staticmethod
    def send_message(chat_id: int, text: str, reply_markup=None, parse_mode="HTML"):
        url = f"{BASE_URL}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        return requests.post(url, json=data).json()

    @staticmethod
    def edit_message(chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode="HTML"):
        url = f"{BASE_URL}/editMessageText"
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        return requests.post(url, json=data).json()

    @staticmethod
    def answer_callback_query(callback_query_id: str, text: str, show_alert=False):
        url = f"{BASE_URL}/answerCallbackQuery"
        data = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert
        }
        return requests.post(url, json=data).json()

    @staticmethod
    def get_chat_member(chat_id, user_id):
        url = f"{BASE_URL}/getChatMember"
        data = {"chat_id": chat_id, "user_id": user_id}
        response = requests.post(url, json=data).json()
        return response

    @staticmethod
    def send_photo(chat_id: int, photo_url: str, caption: str = "", reply_markup=None, parse_mode="HTML"):
        url = f"{BASE_URL}/sendPhoto"
        data = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": parse_mode
        }
        if reply_markup:
            data["reply_markup"] = reply_markup
        return requests.post(url, json=data).json()

    @staticmethod
    def forward_message(chat_id: int, from_chat_id: int, message_id: int):
        url = f"{BASE_URL}/forwardMessage"
        data = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id
        }
        return requests.post(url, json=data).json()

# ============================================================================
# КЛАВИАТУРЫ
# ============================================================================

def get_main_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "👤 Профиль", "callback_data": "profile"}],
            [{"text": "📥 Получить VPN", "callback_data": "get_vpn"}],
            [{"text": "💰 Купить VPN", "callback_data": "buy_vpn"}],
            [{"text": "🏆 Топ Рефералов", "callback_data": "top_referrals"}],
            [{"text": "👥 Пользователи в сети", "callback_data": "users_online"}],
            [{"text": "🎁 Использовать промокод", "callback_data": "use_promo"}]
        ]
    }

def get_profile_keyboard(user_id: int):
    return {
        "inline_keyboard": [
            [{"text": "🔗 Реферальная система", "callback_data": "referral_system"}],
            [{"text": "⬅️ Назад", "callback_data": "back_main"}]
        ]
    }

def get_buy_vpn_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "💳 На месяц - 50 руб", "callback_data": "buy_month"}],
            [{"text": "💳 На год - 150 руб", "callback_data": "buy_year"}],
            [{"text": "💳 На 5 лет - 265 руб", "callback_data": "buy_5years"}],
            [{"text": "⬅️ Назад", "callback_data": "back_main"}]
        ]
    }

def get_admin_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📊 Статистика", "callback_data": "admin_stats"}],
            [{"text": "🔑 Управление VPN", "callback_data": "admin_vpn"}],
            [{"text": "🎁 Промокоды", "callback_data": "admin_promo"}],
            [{"text": "💰 Пополнения", "callback_data": "admin_replenish"}],
            [{"text": "📢 Рассылка", "callback_data": "admin_broadcast"}],
            [{"text": "⬅️ Назад", "callback_data": "back_main"}]
        ]
    }

# ============================================================================
# ФУНКЦИИ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================================

def get_or_create_user(user_id: int, username: str = "", first_name: str = "", last_name: str = ""):
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    if not user:
        referral_code = generate_referral_code(user_id)
        db.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, referral_code) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, last_name, referral_code)
        )
        return db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    return user

def generate_referral_code(user_id: int, length: int = 6):
    chars = string.ascii_letters + string.digits
    code = ''.join(random.choices(chars, k=length))
    
    if db.fetch_one("SELECT * FROM users WHERE referral_code = ?", (code,)):
        return generate_referral_code(user_id, length)
    
    return code

def get_user_profile_text(user_id: int):
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    if not user:
        return "Пользователь не найден"
    
    referral_count = db.fetch_one(
        "SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ?",
        (user_id,)
    )['count']
    
    premium_status = "❌ Нет"
    if user['premium_until']:
        premium_date = datetime.fromisoformat(user['premium_until'])
        if premium_date > datetime.now():
            premium_status = f"✅ До {premium_date.strftime('%d.%m.%Y')}"
        else:
            premium_status = "❌ Истекла"
    
    last_vpn = user['last_free_vpn_date']
    if last_vpn:
        last_vpn_date = datetime.fromisoformat(last_vpn)
        next_vpn_date = last_vpn_date + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
        days_left = (next_vpn_date - datetime.now()).days
        if days_left < 0:
            days_left_text = "✅ Доступно"
        else:
            days_left_text = f"⏳ {days_left} дней"
    else:
        days_left_text = "✅ Доступно"
    
    text = f"""
<b>👤 Ваш профиль</b>

<b>ID:</b> {user['user_id']}
<b>Имя:</b> {user['first_name']} {user['last_name'] or ''}
<b>Юзернейм:</b> @{user['username']}
<b>Дата присоединения:</b> {datetime.fromisoformat(user['joined_date']).strftime('%d.%m.%Y')}

<b>📊 Статистика:</b>
• <b>Рефералов:</b> {referral_count}
• <b>Премиум статус:</b> {premium_status}
• <b>Следующий бесплатный VPN:</b> {days_left_text}
• <b>Реф. код:</b> <code>{user['referral_code']}</code>

<b>🔗 Реферальная ссылка:</b>
<code>https://t.me/{BOT_NAME}?start={user['referral_code']}</code>
    """
    return text.strip()

# ============================================================================
# СИСТЕМА ПРОВЕРКИ ПОДПИСКИ
# ============================================================================

def check_subscription(user_id: int):
    try:
        response = TelegramAPI.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        
        if response.get('ok'):
            status = response['result'].get('status')
            return status in ['member', 'administrator', 'creator']
        
        return False
    except:
        return False

# ============================================================================
# СИСТЕМА КАПЧИ
# ============================================================================

def create_captcha_session(user_id: int, referrer_id: int):
    session_id = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    expires_at = datetime.now() + timedelta(minutes=10)
    
    db.execute(
        "INSERT INTO captcha_sessions (session_id, user_id, referrer_id, expires_at) VALUES (?, ?, ?, ?)",
        (session_id, user_id, referrer_id, expires_at.isoformat())
    )
    
    return session_id

def verify_captcha_session(session_id: str):
    session = db.fetch_one(
        "SELECT * FROM captcha_sessions WHERE session_id = ?",
        (session_id,)
    )
    
    if not session:
        return False, None, None
    
    expires_at = datetime.fromisoformat(session['expires_at'])
    if expires_at < datetime.now():
        return False, None, None
    
    db.execute(
        "UPDATE captcha_sessions SET solved = 1 WHERE session_id = ?",
        (session_id,)
    )
    
    return True, session['user_id'], session['referrer_id']

def get_captcha_keyboard(session_id: str):
    return {
        "inline_keyboard": [
            [{"text": "✅ Я человек", "callback_data": f"captcha_verify_{session_id}"}],
            [{"text": "❌ Отмена", "callback_data": "cancel_registration"}]
        ]
    }

# ============================================================================
# СИСТЕМА РЕФЕРАЛОВ
# ============================================================================

def add_referral(referrer_id: int, referred_user_id: int):
    # Проверка, не добавлена ли уже такая пара
    existing = db.fetch_one(
        "SELECT * FROM referrals WHERE referrer_id = ? AND referred_user_id = ?",
        (referrer_id, referred_user_id)
    )
    
    if existing:
        return False
    
    db.execute(
        "INSERT INTO referrals (referrer_id, referred_user_id) VALUES (?, ?)",
        (referrer_id, referred_user_id)
    )
    
    # Уменьшение кулдауна реферрера на 1 день
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (referrer_id,))
    
    if user['last_free_vpn_date']:
        last_vpn_date = datetime.fromisoformat(user['last_free_vpn_date'])
        new_date = last_vpn_date + timedelta(days=1)
        db.execute(
            "UPDATE users SET last_free_vpn_date = ? WHERE user_id = ?",
            (new_date.isoformat(), referrer_id)
        )
    
    # Отправка уведомления реферреру если включены
    if user['notifications_enabled']:
        message = f"🎉 <b>Новый реферал!</b>\n\nПользователь присоединился через вашу ссылку!\n📊 Ваш кулдаун уменьшен на 1 день."
        TelegramAPI.send_message(referrer_id, message)
    
    return True

def get_top_referrals(limit: int = 10):
    query = """
    SELECT users.user_id, users.first_name, users.username, COUNT(referrals.id) as ref_count
    FROM users
    LEFT JOIN referrals ON users.user_id = referrals.referrer_id
    GROUP BY users.user_id
    ORDER BY ref_count DESC
    LIMIT ?
    """
    return db.fetch_all(query, (limit,))

# ============================================================================
# СИСТЕМА VPN
# ============================================================================

def add_vpn(vpn_address: str, vpn_key: str, vpn_config: str = "", expiry_days: int = 90):
    expiry_date = (datetime.now() + timedelta(days=expiry_days)).isoformat()
    
    db.execute(
        "INSERT INTO vpns (vpn_address, vpn_key, vpn_config, expiry_date) VALUES (?, ?, ?, ?)",
        (vpn_address, vpn_key, vpn_config, expiry_date)
    )
    
    return db.fetch_one("SELECT last_insert_rowid()")

def get_available_vpn(user_id: int):
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    if not user:
        return None
    
    # Получить любой доступный VPN
    vpn = db.fetch_one(
        "SELECT * FROM vpns WHERE is_active = 1 AND expiry_date > ? ORDER BY id DESC LIMIT 1",
        (datetime.now().isoformat(),)
    )
    
    if not vpn:
        return None
    
    # Отметить что VPN дан этому пользователю
    given_users = json.loads(vpn['given_to_users'] or '[]')
    if user_id not in given_users:
        given_users.append(user_id)
        db.execute(
            "UPDATE vpns SET given_to_users = ? WHERE id = ?",
            (json.dumps(given_users), vpn['id'])
        )
    
    return vpn

def get_vpn_stats():
    total = db.fetch_one("SELECT COUNT(*) as count FROM vpns")['count']
    active = db.fetch_one("SELECT COUNT(*) as count FROM vpns WHERE is_active = 1")['count']
    given = db.fetch_one(
        "SELECT COUNT(*) as count FROM vpns WHERE json_array_length(given_to_users) > 0"
    )['count'] if total > 0 else 0
    
    return {"total": total, "active": active, "given": given}

# ============================================================================
# СИСТЕМА ПРОМОКОДОВ
# ============================================================================

def generate_promo_codes(count: int, reward_type: str = "reset_cooldown", usage_limit: int = 1, admin_id: int = ADMIN_ID):
    codes = []
    for _ in range(count):
        code = generate_unique_promo_code()
        db.execute(
            "INSERT INTO promo_codes (code, reward_type, usage_limit, created_by) VALUES (?, ?, ?, ?)",
            (code, reward_type, usage_limit, admin_id)
        )
        codes.append(code)
    
    return codes

def generate_unique_promo_code(length: int = 8):
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choices(chars, k=length))
    
    if db.fetch_one("SELECT * FROM promo_codes WHERE code = ?", (code,)):
        return generate_unique_promo_code(length)
    
    return code

def use_promo_code(user_id: int, code: str):
    promo = db.fetch_one("SELECT * FROM promo_codes WHERE code = ? AND is_active = 1", (code,))
    
    if not promo:
        return False, "❌ Промокод не найден или неактивен"
    
    if promo['usage_limit'] and promo['usage_count'] >= promo['usage_limit']:
        return False, "❌ Промокод использован максимальное количество раз"
    
    if promo['user_id_used'] is not None:
        return False, "❌ Вы уже использовали этот промокод"
    
    # Применить награду
    if promo['reward_type'] == 'reset_cooldown':
        db.execute(
            "UPDATE users SET last_free_vpn_date = NULL WHERE user_id = ?",
            (user_id,)
        )
    
    # Обновить промокод
    db.execute(
        "UPDATE promo_codes SET usage_count = usage_count + 1, user_id_used = ? WHERE code = ?",
        (user_id, code)
    )
    
    return True, "✅ Промокод успешно применен! Кулдаун обнулен."

# ============================================================================
# СИСТЕМА СТАТИСТИКИ
# ============================================================================

def get_bot_stats():
    total_users = db.fetch_one("SELECT COUNT(*) as count FROM users")['count']
    premium_users = db.fetch_one(
        "SELECT COUNT(*) as count FROM users WHERE premium_until > ?",
        (datetime.now().isoformat(),)
    )['count']
    today_users = db.fetch_one(
        "SELECT COUNT(*) as count FROM users WHERE date(joined_date) = date('now')"
    )['count']
    
    return {
        "total_users": total_users,
        "premium_users": premium_users,
        "today_users": today_users
    }

# ============================================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================================

def handle_start_command(message: dict):
    user_id = message['from']['id']
    username = message['from'].get('username', '')
    first_name = message['from'].get('first_name', '')
    last_name = message['from'].get('last_name', '')
    
    # Проверка на реферальную ссылку
    args = message.get('text', '').split()
    
    user = get_or_create_user(user_id, username, first_name, last_name)
    
    # Если есть код реферера
    if len(args) > 1:
        referral_code = args[1]
        referrer = db.fetch_one(
            "SELECT * FROM users WHERE referral_code = ?",
            (referral_code,)
        )
        
        if referrer and referrer['user_id'] != user_id:
            # Если это новый пользователь - показать капчу
            session_id = create_captcha_session(user_id, referrer['user_id'])
            
            captcha_text = f"""
<b>🔐 Подтверждение человека</b>

Уважаемый {first_name}!
Пожалуйста подтвердите что вы человек, нажав кнопку ниже.

После этого вы будете добавлены как реферал пользователя и получите бонус.
            """
            
            TelegramAPI.send_message(
                user_id,
                captcha_text.strip(),
                reply_markup=get_captcha_keyboard(session_id)
            )
            return
        elif referrer and referrer['user_id'] == user_id:
            TelegramAPI.send_message(
                user_id,
                "❌ Вы не можете использовать свою же реферальную ссылку!"
            )
            return
    
    welcome_text = f"""
<b>🎉 Добро пожаловать в {BOT_NAME}!</b>

Я помогу вам получить <b>бесплатные VPN</b> или купить премиум подписку.

<b>📋 Что я умею:</b>
✅ Раздавать бесплатные VPN (1 раз в 3 недели)
✅ Продавать VPN по доступным тарифам
✅ Реферальная система (приглашай друзей, получай бонусы)
✅ Система промокодов и специальных предложений
✅ Профиль с полной статистикой

Нажимайте на кнопки ниже для начала!
    """
    
    TelegramAPI.send_message(
        user_id,
        welcome_text.strip(),
        reply_markup=get_main_keyboard()
    )

def handle_callback_query(callback_query: dict):
    user_id = callback_query['from']['id']
    callback_data = callback_query['data']
    chat_id = callback_query['message']['chat']['id']
    message_id = callback_query['message']['message_id']
    
    # Проверка администратора
    is_admin = user_id == ADMIN_ID
    
    # ========== ОСНОВНОЕ МЕНЮ ==========
    
    if callback_data == "back_main":
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            "Вы вернулись в <b>главное меню</b>",
            reply_markup=get_main_keyboard()
        )
    
    # ========== ПРОФИЛЬ ==========
    
    elif callback_data == "profile":
        user = get_or_create_user(user_id)
        profile_text = get_user_profile_text(user_id)
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            profile_text,
            reply_markup=get_profile_keyboard(user_id)
        )
    
    # ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========
    
    elif callback_data == "referral_system":
        referral_count = db.fetch_one(
            "SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ?",
            (user_id,)
        )['count']
        
        user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        referral_link = f"https://t.me/{BOT_NAME}?start={user['referral_code']}"
        
        referral_text = f"""
<b>🔗 Реферальная система</b>

<b>Как это работает:</b>
1️⃣ Поделитесь своей ссылкой с друзьями
2️⃣ Когда друг присоединится через вашу ссылку
3️⃣ Ваш кулдаун уменьшится на 1 день!

<b>Вы можете получить VPN</b>:
• Бесплатно: 1 раз в 21 день (3 недели)
• С рефералами: 1 раз в 20 дней (на 1 день раньше за каждого реферала)

<b>📊 Ваша статистика:</b>
• Рефералов привлечено: <b>{referral_count}</b>
• Сэкономлено дней: <b>{referral_count}</b>

<b>🔗 Ваша реферальная ссылка:</b>
<code>{referral_link}</code>

Поделитесь этой ссылкой с друзьями и получайте бонусы!
        """
        
        referral_keyboard = {
            "inline_keyboard": [
                [{"text": "📋 Мои рефералы", "callback_data": "my_referrals"}],
                [{"text": "⬅️ Назад", "callback_data": "profile"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            referral_text.strip(),
            reply_markup=referral_keyboard
        )
    
    elif callback_data == "my_referrals":
        referrals = db.fetch_all(
            """
            SELECT users.user_id, users.first_name, users.username, referrals.referred_date
            FROM referrals
            JOIN users ON referrals.referred_user_id = users.user_id
            WHERE referrals.referrer_id = ?
            ORDER BY referrals.referred_date DESC
            """,
            (user_id,)
        )
        
        if not referrals:
            my_referrals_text = "Пока нет рефералов 😔\n\nПозовите друзей по вашей реферальной ссылке!"
        else:
            my_referrals_text = "<b>📋 Ваши рефералы:</b>\n\n"
            for i, ref in enumerate(referrals, 1):
                ref_date = datetime.fromisoformat(ref['referred_date']).strftime('%d.%m.%Y')
                my_referrals_text += f"{i}. @{ref['username']} ({ref['first_name']})\n   Дата: {ref_date}\n\n"
        
        my_referrals_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "referral_system"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            my_referrals_text,
            reply_markup=my_referrals_keyboard
        )
    
    # ========== ПОЛУЧИТЬ VPN ==========
    
    elif callback_data == "get_vpn":
        # Проверка подписки на канал
        is_subscribed = check_subscription(user_id)
        
        if not is_subscribed:
            subscribe_text = f"""
<b>❌ Вы не подписаны на канал!</b>

Для получения бесплатного VPN нужно подписаться на наш канал:
@{CHANNEL_USERNAME}

После подписки нажмите <b>Проверить подписку</b>
            """
            
            subscribe_keyboard = {
                "inline_keyboard": [
                    [{"text": "📢 Подписаться", "url": f"https://t.me/{CHANNEL_USERNAME}"}],
                    [{"text": "✅ Проверить подписку", "callback_data": "check_subscription"}],
                    [{"text": "⬅️ Назад", "callback_data": "back_main"}]
                ]
            }
            
            TelegramAPI.edit_message(
                chat_id,
                message_id,
                subscribe_text.strip(),
                reply_markup=subscribe_keyboard
            )
            return
        
        # Проверка кулдауна
        user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        
        if user['last_free_vpn_date']:
            last_vpn_date = datetime.fromisoformat(user['last_free_vpn_date'])
            next_vpn_date = last_vpn_date + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
            
            if next_vpn_date > datetime.now():
                days_left = (next_vpn_date - datetime.now()).days
                hours_left = ((next_vpn_date - datetime.now()).seconds // 3600)
                
                cooldown_text = f"""
<b>⏳ Подождите перед следующей попыткой</b>

До следующего бесплатного VPN осталось:
<b>{days_left} дней {hours_left} часов</b>

<b>💡 Способы ускорить:</b>
1️⃣ Пригласить реферала (сэкономит 1 день)
2️⃣ Использовать промокод (обнулит кулдаун)
3️⃣ Купить премиум подписку (неограниченные VPN)
                """
                
                speedup_keyboard = {
                    "inline_keyboard": [
                        [{"text": "🎁 Использовать промокод", "callback_data": "use_promo"}],
                        [{"text": "💰 Купить VPN", "callback_data": "buy_vpn"}],
                        [{"text": "⬅️ Назад", "callback_data": "back_main"}]
                    ]
                }
                
                TelegramAPI.edit_message(
                    chat_id,
                    message_id,
                    cooldown_text.strip(),
                    reply_markup=speedup_keyboard
                )
                return
        
        # Получить VPN
        vpn = get_available_vpn(user_id)
        
        if not vpn:
            no_vpn_text = """
<b>❌ VPN временно недоступны</b>

К сожалению, у администратора закончились свободные VPN.
Пожалуйста, попробуйте позже или купите премиум подписку.
            """
            
            TelegramAPI.edit_message(
                chat_id,
                message_id,
                no_vpn_text.strip(),
                reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
            )
            return
        
        # Обновить дату последнего получения VPN
        db.execute(
            "UPDATE users SET last_free_vpn_date = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        
        vpn_text = f"""
<b>✅ Ваш VPN готов!</b>

<b>🔗 Адрес VPN:</b> <code>{vpn['vpn_address']}</code>
<b>🔑 Ключ доступа:</b> <code>{vpn['vpn_key']}</code>

<b>📝 Конфигурация:</b>
<code>{vpn['vpn_config'] or 'Используйте адрес и ключ выше'}</code>

<b>⏰ VPN действителен до:</b> {datetime.fromisoformat(vpn['expiry_date']).strftime('%d.%m.%Y')}

<b>💡 Совет:</b> Пригласите друзей через реферальную систему и получайте VPN чаще!
        """
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            vpn_text.strip(),
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
    
    elif callback_data == "check_subscription":
        if check_subscription(user_id):
            TelegramAPI.answer_callback_query(
                callback_query['id'],
                "✅ Подписка найдена! Попробуйте получить VPN еще раз.",
                show_alert=True
            )
        else:
            TelegramAPI.answer_callback_query(
                callback_query['id'],
                "❌ Подписка не найдена. Пожалуйста подпишитесь на канал!",
                show_alert=True
            )
    
    # ========== КУПИТЬ VPN ==========
    
    elif callback_data == "buy_vpn":
        buy_text = """
<b>💰 Купить VPN</b>

Выберите нужный тариф:

<b>На месяц - 50 рублей</b> (30 дней)
Хороший вариант для пробы

<b>На год - 150 рублей</b> (365 дней)
Лучшее соотношение цены и срока

<b>На 5 лет - 265 рублей</b> (1825 дней)
Супер выгодное предложение!
        """
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            buy_text.strip(),
            reply_markup=get_buy_vpn_keyboard()
        )
    
    elif callback_data.startswith("buy_"):
        tariff = callback_data.replace("buy_", "")
        
        if tariff not in TARIFFS:
            TelegramAPI.answer_callback_query(callback_query['id'], "❌ Неизвестный тариф")
            return
        
        tariff_info = TARIFFS[tariff]
        price = tariff_info['price']
        name = tariff_info['name']
        
        purchase_text = f"""
<b>💳 Оформление покупки</b>

<b>Тариф:</b> {name}
<b>Цена:</b> {price} руб
<b>Срок действия:</b> {tariff_info['duration_days']} дней

<b>⚠️ Способ оплаты:</b>
К сожалению, в этой версии интеграция с платежными системами еще не реализована.

Пожалуйста, свяжитесь с администратором для оформления покупки:
/admin

После оплаты администратор активирует вам премиум статус.
        """
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            purchase_text.strip(),
            reply_markup=get_buy_vpn_keyboard()
        )
    
    # ========== ТОП РЕФЕРАЛОВ ==========
    
    elif callback_data == "top_referrals":
        top_referrals = get_top_referrals(10)
        
        if is_admin:
            top_text = "<b>🏆 Топ Рефералов (Показываю админу)</b>\n\n"
        else:
            top_referrals = [r for r in top_referrals if r['ref_count'] > 0]
            top_text = "<b>🏆 Топ Рефералов</b>\n\n"
        
        if not top_referrals:
            top_text += "Пока никто не привлек рефералов 😔"
        else:
            for i, user in enumerate(top_referrals, 1):
                if user['ref_count'] == 0 and not is_admin:
                    continue
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                top_text += f"{medal} @{user['username']} - <b>{user['ref_count']} рефералов</b>\n"
        
        top_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "back_main"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            top_text,
            reply_markup=top_keyboard
        )
    
    # ========== ПОЛЬЗОВАТЕЛИ В СЕТИ ==========
    
    elif callback_data == "users_online":
        online_users = db.fetch_all(
            """
            SELECT user_id, first_name, username
            FROM users
            WHERE is_online = 1
            ORDER BY last_activity DESC
            LIMIT 20
            """
        )
        
        if is_admin:
            online_text = f"<b>👥 Пользователи в сети (Показываю админу)</b>\n\n<b>Всего в сети: {len(online_users)}</b>\n\n"
        else:
            # Скрыть информацию о конкретных пользователях от обычных пользователей
            online_count = db.fetch_one("SELECT COUNT(*) as count FROM users WHERE is_online = 1")['count']
            online_text = f"<b>👥 Пользователи в сети</b>\n\n<b>Сейчас в сети: {online_count} человек</b>"
        
        if is_admin and online_users:
            online_text += "\n"
            for i, user in enumerate(online_users, 1):
                last_activity = datetime.fromisoformat(user['last_activity']).strftime('%H:%M:%S')
                online_text += f"{i}. @{user['username']} - {last_activity}\n"
        
        online_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "back_main"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            online_text,
            reply_markup=online_keyboard
        )
    
    # ========== ПРОМОКОДЫ ==========
    
    elif callback_data == "use_promo":
        promo_text = """
<b>🎁 Использовать промокод</b>

Введите ваш промокод.

<b>Что дает промокод?</b>
• Обнуление кулдауна на получение VPN
• Бесплатный VPN в любой момент
• Сэкономьте время!

Ожидаю ввод...
        """
        
        TelegramAPI.send_message(
            user_id,
            promo_text.strip(),
            reply_markup={"force_reply": True}
        )
    
    # ========== АДМИНИСТРАТОР ==========
    
    elif callback_data == "admin" and is_admin:
        admin_text = """
<b>⚙️ Админ-панель</b>

Выберите действие:
        """
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            admin_text.strip(),
            reply_markup=get_admin_keyboard()
        )
    
    elif callback_data == "admin_stats" and is_admin:
        stats = get_bot_stats()
        vpn_stats = get_vpn_stats()
        
        stats_text = f"""
<b>📊 Статистика бота</b>

<b>👥 Пользователи:</b>
• Всего: {stats['total_users']}
• Премиум: {stats['premium_users']}
• Присоединилось сегодня: {stats['today_users']}

<b>🔐 VPN:</b>
• Всего в системе: {vpn_stats['total']}
• Активных: {vpn_stats['active']}
• Выданных: {vpn_stats['given']}

<b>🎁 Промокоды:</b>
• Активных: {db.fetch_one('SELECT COUNT(*) as count FROM promo_codes WHERE is_active = 1')['count']}
• Использованных: {db.fetch_one('SELECT COUNT(*) as count FROM promo_codes WHERE usage_count > 0')['count']}
        """
        
        admin_stats_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "admin"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            stats_text.strip(),
            reply_markup=admin_stats_keyboard
        )
    
    elif callback_data == "admin_vpn" and is_admin:
        vpn_text = """
<b>🔑 Управление VPN</b>

Для добавления новых VPN отправьте команду:

/add_vpn <адрес> <ключ> [конфиг]

Пример:
/add_vpn 123.45.67.89 mykey123 config_data

Для просмотра всех VPN:
/list_vpns
        """
        
        admin_vpn_keyboard = {
            "inline_keyboard": [
                [{"text": "📋 Список VPN", "callback_data": "admin_list_vpns"}],
                [{"text": "⬅️ Назад", "callback_data": "admin"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            vpn_text.strip(),
            reply_markup=admin_vpn_keyboard
        )
    
    elif callback_data == "admin_list_vpns" and is_admin:
        vpns = db.fetch_all("SELECT * FROM vpns ORDER BY id DESC LIMIT 20")
        
        if not vpns:
            list_text = "Нет добавленных VPN"
        else:
            list_text = "<b>📋 Список VPN</b>\n\n"
            for vpn in vpns:
                status = "✅" if vpn['is_active'] else "❌"
                expiry = datetime.fromisoformat(vpn['expiry_date']).strftime('%d.%m.%Y')
                list_text += f"{status} <code>{vpn['vpn_address']}</code> (ID: {vpn['id']})\n"
                list_text += f"   До: {expiry}\n\n"
        
        list_vpn_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "admin_vpn"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            list_text,
            reply_markup=list_vpn_keyboard
        )
    
    elif callback_data == "admin_promo" and is_admin:
        promo_text = """
<b>🎁 Управление промокодами</b>

Для создания новых промокодов используйте:

/create_promo <количество> [тип_награды]

Типы наград:
• reset_cooldown - Обнулить кулдаун VPN (по умолчанию)

Пример:
/create_promo 100 reset_cooldown

Это создаст 100 одноразовых промокодов для обнуления кулдауна.

Для просмотра всех промокодов:
/list_promos
        """
        
        admin_promo_keyboard = {
            "inline_keyboard": [
                [{"text": "📋 Список промокодов", "callback_data": "admin_list_promos"}],
                [{"text": "⬅️ Назад", "callback_data": "admin"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            promo_text.strip(),
            reply_markup=admin_promo_keyboard
        )
    
    elif callback_data == "admin_list_promos" and is_admin:
        promos = db.fetch_all(
            "SELECT * FROM promo_codes ORDER BY created_date DESC LIMIT 30"
        )
        
        if not promos:
            promos_list_text = "Нет созданных промокодов"
        else:
            promos_list_text = "<b>🎁 Список промокодов</b>\n\n"
            for promo in promos:
                status = "✅" if promo['is_active'] else "❌"
                used = f"{promo['usage_count']}/{promo['usage_limit']}" if promo['usage_limit'] else f"{promo['usage_count']}/∞"
                promos_list_text += f"{status} <code>{promo['code']}</code> - {used}\n"
        
        list_promos_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "admin_promo"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            promos_list_text,
            reply_markup=list_promos_keyboard
        )
    
    elif callback_data == "admin_replenish" and is_admin:
        replenish_text = """
<b>💰 Пополнение премиум подписок</b>

Для пополнения премиум подписки пользователю используйте:

/give_premium <user_id> <тариф>

Тарифы:
• month - 30 дней
• year - 365 дней
• 5years - 1825 дней

Пример:
/give_premium 123456789 year

Это активирует подписку пользователю на 365 дней.
        """
        
        admin_replenish_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "admin"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            replenish_text.strip(),
            reply_markup=admin_replenish_keyboard
        )
    
    elif callback_data == "admin_broadcast" and is_admin:
        broadcast_text = """
<b>📢 Рассылка сообщений</b>

Для отправки сообщения всем пользователям используйте:

/broadcast <сообщение>

Пример:
/broadcast Внимание! Добавлены новые VPN!

⚠️ Используйте осторожно, рассылается ВСЕМ пользователям!
        """
        
        admin_broadcast_keyboard = {
            "inline_keyboard": [
                [{"text": "⬅️ Назад", "callback_data": "admin"}]
            ]
        }
        
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            broadcast_text.strip(),
            reply_markup=admin_broadcast_keyboard
        )
    
    # ========== КАПЧА ==========
    
    elif callback_data.startswith("captcha_verify_"):
        session_id = callback_data.replace("captcha_verify_", "")
        verified, user_id_from_session, referrer_id = verify_captcha_session(session_id)
        
        if verified:
            # Добавить как реферала
            add_referral(referrer_id, user_id_from_session)
            
            db.execute(
                "UPDATE users SET referrer_id = ? WHERE user_id = ?",
                (referrer_id, user_id_from_session)
            )
            
            success_text = """
<b>✅ Верификация успешна!</b>

Добро пожаловать в {BOT_NAME}!

Вы добавлены как реферал, поэтому:
✅ Сможете получать VPN чаще
✅ Кулдаун вас реферера уменьшен на 1 день
✅ Начните приглашать своих друзей!

Нажимайте кнопки ниже для начала работы.
            """.format(BOT_NAME=BOT_NAME)
            
            TelegramAPI.send_message(
                user_id_from_session,
                success_text.strip(),
                reply_markup=get_main_keyboard()
            )
            
            # Уведомление о решении капчи
            TelegramAPI.send_message(
                user_id,
                "✅ Новый пользователь успешно верифицирован через капчу!"
            )
        else:
            error_text = "❌ Капча истекла или неверна. Пожалуйста, попробуйте еще раз."
            TelegramAPI.answer_callback_query(
                callback_query['id'],
                error_text,
                show_alert=True
            )
    
    elif callback_data == "cancel_registration":
        TelegramAPI.answer_callback_query(
            callback_query['id'],
            "❌ Регистрация отменена",
            show_alert=False
        )

# ============================================================================
# ОБРАБОТЧИКИ ТЕКСТОВЫХ СООБЩЕНИЙ
# ============================================================================

def handle_text_message(message: dict):
    user_id = message['from']['id']
    text = message.get('text', '')
    chat_id = message['chat']['id']
    
    is_admin = user_id == ADMIN_ID
    
    # Проверка на использование промокода
    if message.get('reply_to_message'):
        reply_to = message.get('reply_to_message', {})
        if 'промокод' in reply_to.get('text', '').lower():
            success, message_text = use_promo_code(user_id, text.strip())
            TelegramAPI.send_message(user_id, message_text)
            return
    
    # Проверка на команды админа
    if text.startswith('/'):
        command_parts = text.split()
        command = command_parts[0].lower()
        
        if command == '/admin' and is_admin:
            handle_callback_query({
                'from': message['from'],
                'data': 'admin',
                'message': message,
                'id': str(random.randint(1000000, 9999999))
            })
            return
        
        elif command == '/add_vpn' and is_admin:
            if len(command_parts) < 3:
                TelegramAPI.send_message(
                    user_id,
                    "❌ Неправильный синтаксис!\n\nИспользуйте: /add_vpn <адрес> <ключ> [конфиг]"
                )
                return
            
            vpn_address = command_parts[1]
            vpn_key = command_parts[2]
            vpn_config = ' '.join(command_parts[3:]) if len(command_parts) > 3 else ""
            
            add_vpn(vpn_address, vpn_key, vpn_config)
            
            admin_log = f"Добавлен новый VPN: {vpn_address}"
            db.execute(
                "INSERT INTO admin_logs (admin_id, action, details) VALUES (?, ?, ?)",
                (user_id, 'add_vpn', admin_log)
            )
            
            TelegramAPI.send_message(
                user_id,
                f"✅ VPN успешно добавлен!\n\n🔗 Адрес: {vpn_address}\n🔑 Ключ: {vpn_key}"
            )
            
            # Отправить уведомление об обновлении VPN
            broadcast_message = "📢 <b>Обновление!</b>\n\nАдминистратор добавил новые VPN!\n\n✅ Получить VPN можно в меню бота."
            broadcast_all_users(broadcast_message)
            return
        
        elif command == '/list_vpns' and is_admin:
            vpns = db.fetch_all("SELECT * FROM vpns ORDER BY id DESC LIMIT 50")
            
            if not vpns:
                TelegramAPI.send_message(user_id, "Нет добавленных VPN")
                return
            
            vpn_list = "<b>📋 Все VPN:</b>\n\n"
            for vpn in vpns:
                status = "✅ Активный" if vpn['is_active'] else "❌ Неактивный"
                given_count = len(json.loads(vpn['given_to_users'] or '[]'))
                expiry = datetime.fromisoformat(vpn['expiry_date']).strftime('%d.%m.%Y')
                
                vpn_list += f"ID {vpn['id']}: {status}\n"
                vpn_list += f"📍 {vpn['vpn_address']}\n"
                vpn_list += f"Выдано: {given_count} | До: {expiry}\n\n"
            
            TelegramAPI.send_message(user_id, vpn_list)
            return
        
        elif command == '/create_promo' and is_admin:
            if len(command_parts) < 2:
                TelegramAPI.send_message(
                    user_id,
                    "❌ Неправильный синтаксис!\n\nИспользуйте: /create_promo <количество> [тип]"
                )
                return
            
            try:
                count = int(command_parts[1])
                reward_type = command_parts[2] if len(command_parts) > 2 else 'reset_cooldown'
                
                if count > 1000:
                    TelegramAPI.send_message(
                        user_id,
                        "❌ Максимум 1000 промокодов за раз!"
                    )
                    return
                
                codes = generate_promo_codes(count, reward_type, 1, user_id)
                
                codes_text = "✅ Промокоды успешно созданы!\n\n"
                codes_text += "Первые 10 кодов:\n"
                for i, code in enumerate(codes[:10], 1):
                    codes_text += f"{i}. <code>{code}</code>\n"
                codes_text += f"\n... и еще {count - 10} кодов\n\n"
                codes_text += f"🎁 Тип: {reward_type}\n"
                codes_text += f"📊 Всего создано: {count}"
                
                TelegramAPI.send_message(user_id, codes_text)
                
                admin_log = f"Создано {count} промокодов тип {reward_type}"
                db.execute(
                    "INSERT INTO admin_logs (admin_id, action, details) VALUES (?, ?, ?)",
                    (user_id, 'create_promo', admin_log)
                )
                
            except ValueError:
                TelegramAPI.send_message(
                    user_id,
                    "❌ Количество должно быть числом!"
                )
            return
        
        elif command == '/list_promos' and is_admin:
            promos = db.fetch_all(
                "SELECT * FROM promo_codes ORDER BY created_date DESC LIMIT 50"
            )
            
            if not promos:
                TelegramAPI.send_message(user_id, "Нет созданных промокодов")
                return
            
            promos_text = "<b>🎁 Все промокоды:</b>\n\n"
            for promo in promos:
                status = "✅" if promo['is_active'] else "❌"
                used = f"{promo['usage_count']}/{promo['usage_limit']}" if promo['usage_limit'] else f"{promo['usage_count']}/∞"
                promos_text += f"{status} <code>{promo['code']}</code>\n"
                promos_text += f"   Тип: {promo['reward_type']} | {used}\n"
            
            TelegramAPI.send_message(user_id, promos_text)
            return
        
        elif command == '/give_premium' and is_admin:
            if len(command_parts) < 3:
                TelegramAPI.send_message(
                    user_id,
                    "❌ Неправильный синтаксис!\n\nИспользуйте: /give_premium <user_id> <тариф>"
                )
                return
            
            try:
                target_user_id = int(command_parts[1])
                tariff = command_parts[2].lower()
                
                if tariff not in TARIFFS:
                    TelegramAPI.send_message(
                        user_id,
                        f"❌ Неизвестный тариф! Доступные: {', '.join(TARIFFS.keys())}"
                    )
                    return
                
                tariff_info = TARIFFS[tariff]
                premium_until = datetime.now() + timedelta(days=tariff_info['duration_days'])
                
                db.execute(
                    "UPDATE users SET premium_until = ? WHERE user_id = ?",
                    (premium_until.isoformat(), target_user_id)
                )
                
                # Записать покупку
                db.execute(
                    "INSERT INTO purchases (user_id, tariff, price, premium_until) VALUES (?, ?, ?, ?)",
                    (target_user_id, tariff, tariff_info['price'], premium_until.isoformat())
                )
                
                # Уведомить пользователя
                user_message = f"""
✅ <b>Вам активирована премиум подписка!</b>

📅 Тариф: {tariff_info['name']}
💰 Сумма: {tariff_info['price']} рублей
⏰ Действует до: {premium_until.strftime('%d.%m.%Y')}

🎉 Спасибо за поддержку!
                """
                
                TelegramAPI.send_message(target_user_id, user_message.strip())
                
                TelegramAPI.send_message(
                    user_id,
                    f"✅ Премиум активирован пользователю {target_user_id}"
                )
                
                admin_log = f"Активирована премиум подписка {target_user_id} тариф {tariff}"
                db.execute(
                    "INSERT INTO admin_logs (admin_id, action, details) VALUES (?, ?, ?)",
                    (user_id, 'give_premium', admin_log)
                )
                
            except ValueError:
                TelegramAPI.send_message(
                    user_id,
                    "❌ User ID должен быть числом!"
                )
            return
        
        elif command == '/broadcast' and is_admin:
            if len(command_parts) < 2:
                TelegramAPI.send_message(
                    user_id,
                    "❌ Укажите сообщение!\n\nИспользуйте: /broadcast <сообщение>"
                )
                return
            
            broadcast_text = ' '.join(command_parts[1:])
            
            broadcast_all_users(broadcast_text)
            
            TelegramAPI.send_message(
                user_id,
                "✅ Рассылка отправлена всем пользователям!"
            )
            
            admin_log = f"Отправлена рассылка: {broadcast_text[:50]}"
            db.execute(
                "INSERT INTO admin_logs (admin_id, action, details) VALUES (?, ?, ?)",
                (user_id, 'broadcast', admin_log)
            )
            return
        
        elif command == '/stats' and is_admin:
            stats = get_bot_stats()
            vpn_stats = get_vpn_stats()
            
            stats_message = f"""
<b>📊 Статистика бота:</b>

👥 Пользователи: {stats['total_users']}
💎 Премиум: {stats['premium_users']}
🆕 Сегодня: {stats['today_users']}

🔐 VPN: {vpn_stats['total']} всего, {vpn_stats['active']} активных
🎁 Промокодов: {db.fetch_one('SELECT COUNT(*) FROM promo_codes WHERE is_active = 1')['COUNT(*)']}
            """
            
            TelegramAPI.send_message(user_id, stats_message)
            return
        
        else:
            TelegramAPI.send_message(
                user_id,
                "❌ Неизвестная команда!\n\nДоступные команды:\n/admin - админ-панель\n/stats - статистика"
            )
            return

def broadcast_all_users(message_text: str):
    users = db.fetch_all("SELECT user_id FROM users")
    
    for user in users:
        try:
            TelegramAPI.send_message(user['user_id'], message_text)
            time.sleep(0.1)  # Задержка чтобы не заспамить API
        except:
            pass

# ============================================================================
# ВЕБХУК/ПОЛИНГ
# ============================================================================

def process_update(update: dict):
    """Обработать входящее обновление от Telegram"""
    
    # Обновить статус пользователя
    if 'message' in update:
        user_id = update['message']['from']['id']
        db.execute(
            "UPDATE users SET is_online = 1, last_activity = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        
        if update['message'].get('text') and update['message']['text'].startswith('/start'):
            handle_start_command(update['message'])
        else:
            handle_text_message(update['message'])
    
    elif 'callback_query' in update:
        user_id = update['callback_query']['from']['id']
        db.execute(
            "UPDATE users SET is_online = 1, last_activity = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        
        handle_callback_query(update['callback_query'])

def get_updates(timeout: int = 30):
    """Получить обновления от Telegram"""
    url = f"{BASE_URL}/getUpdates"
    
    offset = 0
    
    while True:
        try:
            response = requests.post(
                url,
                json={"offset": offset, "timeout": timeout},
                timeout=timeout + 5
            ).json()
            
            if response.get('ok'):
                for update in response.get('result', []):
                    offset = update['update_id'] + 1
                    process_update(update)
                    
        except Exception as e:
            print(f"Ошибка при получении обновлений: {e}")
            time.sleep(5)

# ============================================================================
# ГЛАВНАЯ ПРОГРАММА
# ============================================================================

if __name__ == "__main__":
    print(f"✅ Бот {BOT_NAME} запущен!")
    print(f"🔑 Админ ID: {ADMIN_ID}")
    print(f"📢 Канал: @{CHANNEL_USERNAME}")
    print(f"📝 Используется база данных: vpn_bot.db")
    print("\n🚀 Начинаю слушать сообщения...\n")
    
    # Запустить получение обновлений
    get_updates()
