import requests
import json
import time
import random
import string
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# ============================================================================
# КОНФИГУРАЦИЯ БОТА
# ============================================================================

BOT_TOKEN = "8497365873:AAEbquvUEc79JmTtuJHqHGu_Rm0Uzi5A1-s"
ADMIN_ID = 7694543415
CHANNEL_USERNAME = "LogovoDextera"
BOT_NAME = "DexterFreeVpn"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Параметры системы
FREE_VPN_COOLDOWN_DAYS = 21  # 3 недели

# Тарифы (только 3)
TARIFFS = {
    "month": {"price": 50, "duration_days": 30, "name": "📅 Месяц"},
    "year": {"price": 150, "duration_days": 365, "name": "🗓 Год"},
    "5years": {"price": 250, "duration_days": 1825, "name": "🎯 5 лет"}
}

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
                premium_until TIMESTAMP,
                is_subscribed BOOLEAN DEFAULT 0,
                notifications_enabled BOOLEAN DEFAULT 1,
                is_online BOOLEAN DEFAULT 0,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица VPN ссылок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vpn_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT NOT NULL UNIQUE,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                given_count INTEGER DEFAULT 0
            )
        ''')

        # История получения VPN
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vpn_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                link TEXT NOT NULL,
                received_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        # Реферальная система
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL UNIQUE,
                referred_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                bonus_applied BOOLEAN DEFAULT 0,
                FOREIGN KEY(referrer_id) REFERENCES users(user_id),
                FOREIGN KEY(referred_user_id) REFERENCES users(user_id)
            )
        ''')

        # Промокоды
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                usage_limit INTEGER,
                usage_count INTEGER DEFAULT 0,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')

        # Использованные промокоды пользователями
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                promo_code TEXT NOT NULL,
                used_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, promo_code),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        # Покупки
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tariff TEXT NOT NULL,
                price REAL NOT NULL,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                premium_until TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        # Логи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

db = Database()

# ============================================================================
# TELEGRAM API
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

# ============================================================================
# КЛАВИАТУРЫ
# ============================================================================

def get_main_keyboard(is_admin=False):
    keyboard = {
        "inline_keyboard": [
            [{"text": "📥 Получить VPN", "callback_data": "get_vpn"}],
            [{"text": "💳 Купить доступ", "callback_data": "buy_vpn"}],
            [{"text": "👤 Профиль", "callback_data": "profile"}],
            [{"text": "📊 Статистика", "callback_data": "statistics"}],
            [{"text": "🏆 Топ рефералов", "callback_data": "top_referrals"}]
        ]
    }
    
    if is_admin:
        keyboard["inline_keyboard"].insert(0, [{"text": "⚙️ Админ-панель", "callback_data": "admin"}])
    
    return keyboard

def get_profile_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔗 Реферальная система", "callback_data": "referral_system"}],
            [{"text": "🎁 Ввести промокод", "callback_data": "enter_promo"}],
            [{"text": "⬅️ Назад", "callback_data": "back_main"}]
        ]
    }

def get_buy_keyboard():
    keyboard = {"inline_keyboard": []}
    for tariff_key, tariff_info in TARIFFS.items():
        keyboard["inline_keyboard"].append([
            {
                "text": f"{tariff_info['name']} - {tariff_info['price']} руб",
                "callback_data": f"buy_{tariff_key}"
            }
        ])
    keyboard["inline_keyboard"].append([{"text": "⬅️ Назад", "callback_data": "back_main"}])
    return keyboard

def get_admin_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📥 Загрузить VPN", "callback_data": "admin_add_vpn"}],
            [{"text": "📋 Список VPN", "callback_data": "admin_list_vpn"}],
            [{"text": "🎁 Промокоды", "callback_data": "admin_promo"}],
            [{"text": "📊 Админ статистика", "callback_data": "admin_stats"}],
            [{"text": "📢 Рассылка", "callback_data": "admin_broadcast"}],
            [{"text": "⬅️ Назад", "callback_data": "back_main"}]
        ]
    }

# ============================================================================
# ПОЛЬЗОВАТЕЛЬСКИЕ ФУНКЦИИ
# ============================================================================

def generate_referral_code(user_id: int, length: int = 8):
    chars = string.ascii_letters + string.digits
    code = ''.join(random.choices(chars, k=length))
    
    existing = db.fetch_one("SELECT * FROM users WHERE referral_code = ?", (code,))
    if existing:
        return generate_referral_code(user_id, length)
    
    return code

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

def check_subscription(user_id: int):
    try:
        response = TelegramAPI.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        
        if response.get('ok'):
            status = response['result'].get('status')
            return status in ['member', 'administrator', 'creator']
        
        return False
    except:
        return False

def add_referral(referrer_id: int, referred_user_id: int):
    # Проверка что не добавлен
    existing = db.fetch_one(
        "SELECT * FROM referrals WHERE referred_user_id = ?",
        (referred_user_id,)
    )
    
    if existing or referrer_id == referred_user_id:
        return False
    
    # Добавить
    db.execute(
        "INSERT INTO referrals (referrer_id, referred_user_id, bonus_applied) VALUES (?, ?, 1)",
        (referrer_id, referred_user_id)
    )
    
    # Уменьшить кулдаун реферреру на 1 день
    referrer = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (referrer_id,))
    
    if referrer['last_free_vpn_date']:
        last_date = datetime.fromisoformat(referrer['last_free_vpn_date'])
        # Минус 1 день от последней даты (то есть раньше сможет получить)
        new_date = last_date - timedelta(days=1)
        db.execute(
            "UPDATE users SET last_free_vpn_date = ? WHERE user_id = ?",
            (new_date.isoformat(), referrer_id)
        )
    
    # Уведомление
    if referrer['notifications_enabled']:
        notify_text = f"""🎉 <b>Новый реферал!</b>

Пользователь присоединился по вашей ссылке!
✅ Ваш кулдаун уменьшен на 1 день.
        """
        TelegramAPI.send_message(referrer_id, notify_text.strip())
    
    return True

def get_user_profile_text(user_id: int):
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    if not user:
        return "Пользователь не найден"
    
    # Премиум статус
    premium_status = "❌ Нет"
    if user['premium_until']:
        premium_date = datetime.fromisoformat(user['premium_until'])
        if premium_date > datetime.now():
            premium_status = f"✅ До {premium_date.strftime('%d.%m.%Y')}"
        else:
            premium_status = "❌ Истёк"
    
    # Кулдаун
    if user['last_free_vpn_date']:
        last_vpn_date = datetime.fromisoformat(user['last_free_vpn_date'])
        next_vpn_date = last_vpn_date + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
        
        if next_vpn_date > datetime.now():
            days_left = (next_vpn_date - datetime.now()).days
            hours_left = ((next_vpn_date - datetime.now()).seconds // 3600)
            cooldown_text = f"⏳ {days_left} д {hours_left} ч"
        else:
            cooldown_text = "✅ Доступно"
    else:
        cooldown_text = "✅ Доступно"
    
    # Рефералы
    referral_count = db.fetch_one(
        "SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ?",
        (user_id,)
    )['count']
    
    text = f"""
<b>👤 Ваш профиль</b>

<b>ID:</b> {user['user_id']}
<b>Имя:</b> {user['first_name']} {user['last_name'] or ''}
<b>Username:</b> @{user['username'] or 'не указан'}

<b>📊 Статистика:</b>
• <b>Присоединился:</b> {datetime.fromisoformat(user['joined_date']).strftime('%d.%m.%Y')}
• <b>Премиум:</b> {premium_status}
• <b>Бесплатный VPN:</b> {cooldown_text}
• <b>Рефералов привлечено:</b> {referral_count}

<b>🔗 Реферальный код:</b> <code>{user['referral_code']}</code>
    """
    return text.strip()

def get_statistics_text():
    total_users = db.fetch_one("SELECT COUNT(*) as count FROM users")['count']
    total_vpns = db.fetch_one("SELECT COUNT(*) as count FROM vpn_links WHERE is_active = 1")['count']
    
    # Выдано всего
    total_given = db.fetch_one(
        "SELECT SUM(given_count) as total FROM vpn_links"
    )['total'] or 0
    
    # За сегодня
    today_given = db.fetch_one(
        "SELECT COUNT(*) as count FROM vpn_history WHERE date(received_date) = date('now')"
    )['count']
    
    # За месяц
    month_given = db.fetch_one(
        "SELECT COUNT(*) as count FROM vpn_history WHERE date(received_date) >= date('now', '-30 days')"
    )['count']
    
    text = f"""
<b>📊 Статистика бота</b>

<b>👥 Пользователи:</b>
• Всего: {total_users}

<b>🔗 VPN:</b>
• Всего выдано: {total_given}
• Доступно сейчас: {total_vpns}
• Выдано за сегодня: {today_given}
• Выдано за месяц: {month_given}
    """
    return text.strip()

def get_top_referrals_text():
    top = db.fetch_all("""
        SELECT users.user_id, users.first_name, users.username, COUNT(referrals.id) as ref_count
        FROM users
        LEFT JOIN referrals ON users.user_id = referrals.referrer_id
        GROUP BY users.user_id
        HAVING ref_count > 0
        ORDER BY ref_count DESC
        LIMIT 10
    """)
    
    if not top:
        return "<b>🏆 Топ рефералов</b>\n\nПока никто не привлёк рефералов."
    
    text = "<b>🏆 Топ 10 рефералов</b>\n\n"
    for i, user in enumerate(top, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = user['first_name']
        username = f"@{user['username']}" if user['username'] else ""
        text += f"{medal} {name} {username} - <b>{user['ref_count']}</b> реф.\n"
    
    return text.strip()

# ============================================================================
# ПРОМОКОДЫ
# ============================================================================

def generate_promo_code(length: int = 8):
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choices(chars, k=length))
    
    existing = db.fetch_one("SELECT * FROM promo_codes WHERE code = ?", (code,))
    if existing:
        return generate_promo_code(length)
    
    return code

def create_promo_codes(count: int, usage_limit: int = None):
    codes = []
    for _ in range(count):
        code = generate_promo_code()
        db.execute(
            "INSERT INTO promo_codes (code, usage_limit) VALUES (?, ?)",
            (code, usage_limit)
        )
        codes.append(code)
    
    return codes

def use_promo_code(user_id: int, code: str):
    # Проверить промокод
    promo = db.fetch_one(
        "SELECT * FROM promo_codes WHERE code = ? AND is_active = 1",
        (code.upper(),)
    )
    
    if not promo:
        return False, "❌ Промокод не найден или неактивен."
    
    # Проверить лимит
    if promo['usage_limit'] and promo['usage_count'] >= promo['usage_limit']:
        return False, "❌ Промокод использован максимальное количество раз."
    
    # Проверить использовал ли пользователь
    used = db.fetch_one(
        "SELECT * FROM promo_usage WHERE user_id = ? AND promo_code = ?",
        (user_id, code.upper())
    )
    
    if used:
        return False, "❌ Вы уже использовали этот промокод."
    
    # Применить - обнулить кулдаун
    db.execute(
        "UPDATE users SET last_free_vpn_date = NULL WHERE user_id = ?",
        (user_id,)
    )
    
    # Отметить использование
    db.execute(
        "INSERT INTO promo_usage (user_id, promo_code) VALUES (?, ?)",
        (user_id, code.upper())
    )
    
    # Обновить счетчик
    db.execute(
        "UPDATE promo_codes SET usage_count = usage_count + 1 WHERE code = ?",
        (code.upper(),)
    )
    
    return True, "✅ Промокод применён! Кулдаун обнулён."

# ============================================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================================

def handle_start_command(message: dict):
    user_id = message['from']['id']
    username = message['from'].get('username', '')
    first_name = message['from'].get('first_name', '')
    last_name = message['from'].get('last_name', '')
    
    # Проверка реферального кода
    args = message.get('text', '').split()
    
    user = get_or_create_user(user_id, username, first_name, last_name)
    
    if len(args) > 1:
        ref_code = args[1]
        referrer = db.fetch_one(
            "SELECT * FROM users WHERE referral_code = ?",
            (ref_code,)
        )
        
        if referrer and referrer['user_id'] != user_id:
            # Проверить не добавлен ли уже
            already = db.fetch_one(
                "SELECT * FROM users WHERE user_id = ? AND referrer_id IS NOT NULL",
                (user_id,)
            )
            
            if not already:
                db.execute(
                    "UPDATE users SET referrer_id = ? WHERE user_id = ?",
                    (referrer['user_id'], user_id)
                )
                add_referral(referrer['user_id'], user_id)
    
    is_admin = user_id == ADMIN_ID
    
    welcome_text = f"""
<b>🎉 Добро пожаловать в {BOT_NAME}!</b>

Это бот для раздачи бесплатных VPN!

<b>📋 Возможности:</b>
✅ Получайте бесплатные VPN (1 раз в 3 недели)
✅ Приглашайте друзей - уменьшайте кулдаун
✅ Используйте промокоды для обнуления кулдауна
✅ Покупайте премиум для безлимитного доступа
✅ Смотрите статистику и топ рефералов

<b>📢 Подпишитесь на канал:</b> @{CHANNEL_USERNAME}

Выберите действие ниже:
    """
    
    TelegramAPI.send_message(
        user_id,
        welcome_text.strip(),
        reply_markup=get_main_keyboard(is_admin)
    )

def handle_callback_query(callback_query: dict):
    user_id = callback_query['from']['id']
    callback_data = callback_query['data']
    chat_id = callback_query['message']['chat']['id']
    message_id = callback_query['message']['message_id']
    
    is_admin = user_id == ADMIN_ID
    
    # ========== ОСНОВНОЕ МЕНЮ ==========
    
    if callback_data == "back_main":
        TelegramAPI.edit_message(
            chat_id, message_id,
            "📱 <b>Главное меню</b>\n\nВыберите действие:",
            reply_markup=get_main_keyboard(is_admin)
        )
    
    # ========== ПОЛУЧИТЬ VPN ==========
    
    elif callback_data == "get_vpn":
        user = get_or_create_user(user_id)
        
        # Проверка подписки
        if not check_subscription(user_id):
            TelegramAPI.answer_callback_query(
                callback_query['id'],
                f"❌ Подпишитесь на @{CHANNEL_USERNAME} перед получением VPN!",
                show_alert=True
            )
            return
        
        # Проверка премиума
        has_premium = False
        if user['premium_until']:
            premium_date = datetime.fromisoformat(user['premium_until'])
            has_premium = premium_date > datetime.now()
        
        # Проверка кулдауна (если нет премиума)
        if not has_premium:
            if user['last_free_vpn_date']:
                last_vpn_date = datetime.fromisoformat(user['last_free_vpn_date'])
                next_vpn_date = last_vpn_date + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
                
                if next_vpn_date > datetime.now():
                    days_left = (next_vpn_date - datetime.now()).days
                    hours_left = ((next_vpn_date - datetime.now()).seconds // 3600)
                    
                    cooldown_text = f"""
<b>⏳ Кулдаун активен</b>

До следующего бесплатного VPN осталось:
<b>{days_left} дней {hours_left} часов</b>

<b>💡 Хотите получить раньше?</b>
• Пригласите друзей (-1 день за каждого)
• Используйте промокод (обнуление кулдауна)
• Купите премиум доступ
                    """
                    
                    TelegramAPI.edit_message(
                        chat_id, message_id,
                        cooldown_text.strip(),
                        reply_markup={
                            "inline_keyboard": [
                                [{"text": "💳 Купить доступ", "callback_data": "buy_vpn"}],
                                [{"text": "🎁 Ввести промокод", "callback_data": "enter_promo"}],
                                [{"text": "⬅️ Назад", "callback_data": "back_main"}]
                            ]
                        }
                    )
                    return
        
        # Получить VPN
        vpn_link = db.fetch_one(
            "SELECT * FROM vpn_links WHERE is_active = 1 ORDER BY RANDOM() LIMIT 1"
        )
        
        if not vpn_link:
            TelegramAPI.edit_message(
                chat_id, message_id,
                "❌ <b>VPN временно недоступны</b>\n\nАдминистратор ещё не добавил ссылки.",
                reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
            )
            return
        
        # Обновить дату
        if not has_premium:
            db.execute(
                "UPDATE users SET last_free_vpn_date = ? WHERE user_id = ?",
                (datetime.now().isoformat(), user_id)
            )
        
        # Добавить в историю
        db.execute(
            "INSERT INTO vpn_history (user_id, link) VALUES (?, ?)",
            (user_id, vpn_link['link'])
        )
        
        # Обновить счетчик
        db.execute(
            "UPDATE vpn_links SET given_count = given_count + 1 WHERE id = ?",
            (vpn_link['id'],)
        )
        
        vpn_text = f"""
<b>✅ Ваша VPN ссылка!</b>

<code>{vpn_link['link']}</code>

<b>📋 Инструкция:</b>
1. Скопируйте ссылку
2. Откройте приложение VPN
3. Импортируйте конфиг
4. Подключитесь!

⏰ Следующая ссылка через 3 недели.
💡 Пригласите друзей - получайте раньше!
        """
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            vpn_text.strip(),
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
    
    # ========== КУПИТЬ VPN ==========
    
    elif callback_data == "buy_vpn":
        buy_text = """
<b>💳 Выберите тариф</b>

Премиум доступ позволит получать VPN без ограничений!
        """
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            buy_text.strip(),
            reply_markup=get_buy_keyboard()
        )
    
    elif callback_data.startswith("buy_"):
        tariff = callback_data.replace("buy_", "")
        
        if tariff not in TARIFFS:
            return
        
        tariff_info = TARIFFS[tariff]
        
        purchase_text = f"""
<b>💳 Оформление покупки</b>

<b>Тариф:</b> {tariff_info['name']}
<b>Цена:</b> {tariff_info['price']} руб
<b>Действителен:</b> {tariff_info['duration_days']} дней

<b>📝 Способ оплаты:</b>
Свяжитесь с @{CHANNEL_USERNAME} для оформления.

Передайте администратору:
• <b>Ваш ID:</b> <code>{user_id}</code>
• <b>Тариф:</b> {tariff_info['name']}
• <b>Цена:</b> {tariff_info['price']} руб
        """
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            purchase_text.strip(),
            reply_markup={
                "inline_keyboard": [
                    [{"text": "💬 Написать администратору", "url": f"https://t.me/{CHANNEL_USERNAME}"}],
                    [{"text": "⬅️ Назад", "callback_data": "buy_vpn"}]
                ]
            }
        )
    
    # ========== ПРОФИЛЬ ==========
    
    elif callback_data == "profile":
        profile_text = get_user_profile_text(user_id)
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            profile_text,
            reply_markup=get_profile_keyboard()
        )
    
    elif callback_data == "referral_system":
        user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        referral_count = db.fetch_one(
            "SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ?",
            (user_id,)
        )['count']
        
        referral_link = f"https://t.me/{BOT_NAME}?start={user['referral_code']}"
        
        ref_text = f"""
<b>🔗 Реферальная система</b>

<b>Как это работает:</b>
1. Поделитесь вашей ссылкой с друзьями
2. Когда друг присоединяется - у вас минус 1 день кулдауна!
3. Чем больше рефералов, тем чаще получаете VPN

<b>📊 Ваша статистика:</b>
• Приглашено: <b>{referral_count}</b> чел.
• Сэкономлено: <b>{referral_count}</b> дней

<b>🔗 Ваша реферальная ссылка:</b>
<code>{referral_link}</code>
        """
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            ref_text.strip(),
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "profile"}]]}
        )
    
    elif callback_data == "enter_promo":
        promo_text = """
<b>🎁 Введите промокод</b>

Отправьте промокод следующим сообщением.

<b>Что даёт промокод:</b>
✅ Обнуление кулдауна
✅ Возможность получить VPN сразу
        """
        
        TelegramAPI.send_message(
            user_id,
            promo_text.strip(),
            reply_markup={"force_reply": True}
        )
    
    # ========== СТАТИСТИКА ==========
    
    elif callback_data == "statistics":
        stats_text = get_statistics_text()
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            stats_text,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
    
    # ========== ТОП РЕФЕРАЛОВ ==========
    
    elif callback_data == "top_referrals":
        top_text = get_top_referrals_text()
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            top_text,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
    
    # ========== АДМИН-ПАНЕЛЬ ==========
    
    elif callback_data == "admin" and is_admin:
        admin_text = "<b>⚙️ Администраторская панель</b>\n\nВыберите действие:"
        TelegramAPI.edit_message(
            chat_id, message_id,
            admin_text,
            reply_markup=get_admin_keyboard()
        )
    
    elif callback_data == "admin_add_vpn" and is_admin:
        add_vpn_text = """
<b>📥 Загрузка VPN ссылок</b>

Отправьте ссылки следующим образом:

<code>Ссылка 1
Ссылка 2
Ссылка 3</code>

Либо одну ссылку в сообщении.
        """
        
        TelegramAPI.send_message(
            user_id,
            add_vpn_text.strip(),
            reply_markup={"force_reply": True}
        )
    
    elif callback_data == "admin_list_vpn" and is_admin:
        vpn_links = db.fetch_all(
            "SELECT * FROM vpn_links WHERE is_active = 1 ORDER BY added_date DESC LIMIT 20"
        )
        
        if not vpn_links:
            list_text = "❌ VPN ссылок нет"
        else:
            list_text = f"<b>📋 VPN Ссылки ({len(vpn_links)})</b>\n\n"
            for i, vpn in enumerate(vpn_links, 1):
                list_text += f"{i}. <code>{vpn['link'][:50]}...</code>\n   Выдано: {vpn['given_count']} раз\n\n"
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            list_text,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "admin"}]]}
        )
    
    elif callback_data == "admin_promo" and is_admin:
        promo_text = """
<b>🎁 Управление промокодами</b>

Доступные команды:

/create_promo <кол-во> [лимит]

Пример:
/create_promo 10 - создать 10 одноразовых
/create_promo 5 100 - создать 5 на 100 активаций
        """
        
        TelegramAPI.send_message(user_id, promo_text.strip())
    
    elif callback_data == "admin_stats" and is_admin:
        total_users = db.fetch_one("SELECT COUNT(*) as count FROM users")['count']
        total_vpns = db.fetch_one("SELECT COUNT(*) as count FROM vpn_links WHERE is_active = 1")['count']
        today_users = db.fetch_one(
            "SELECT COUNT(*) as count FROM users WHERE date(joined_date) = date('now')"
        )['count']
        
        stats_text = f"""
<b>📊 Админ статистика</b>

<b>👥 Пользователи:</b>
• Всего: {total_users}
• Новых сегодня: {today_users}

<b>🔗 VPN:</b>
• Активных ссылок: {total_vpns}
        """
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            stats_text.strip(),
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "admin"}]]}
        )
    
    elif callback_data == "admin_broadcast" and is_admin:
        broadcast_text = """
<b>📢 Рассылка</b>

Отправьте сообщение которое хотите разослать всем пользователям.
        """
        
        TelegramAPI.send_message(
            user_id,
            broadcast_text.strip(),
            reply_markup={"force_reply": True}
        )

# ============================================================================
# ОБРАБОТЧИКИ ТЕКСТОВЫХ СООБЩЕНИЙ
# ============================================================================

def handle_text_message(message: dict):
    user_id = message['from']['id']
    text = message.get('text', '')
    is_admin = user_id == ADMIN_ID
    
    # Команды админа
    if text.startswith('/') and is_admin:
        command_parts = text.split()
        command = command_parts[0].lower()
        
        if command == '/admin':
            handle_callback_query({
                'from': message['from'],
                'data': 'admin',
                'message': message,
                'id': str(random.randint(1000000, 9999999))
            })
            return
        
        elif command == '/create_promo':
            if len(command_parts) < 2:
                TelegramAPI.send_message(
                    user_id,
                    "❌ Использование: /create_promo <кол-во> [лимит]"
                )
                return
            
            try:
                count = int(command_parts[1])
                limit = int(command_parts[2]) if len(command_parts) > 2 else 1
                
                codes = create_promo_codes(count, limit)
                
                codes_text = f"✅ <b>Создано {count} промокодов!</b>\n\n"
                codes_text += "Первые 10:\n"
                for i, code in enumerate(codes[:10], 1):
                    codes_text += f"{i}. <code>{code}</code>\n"
                if count > 10:
                    codes_text += f"\n... и ещё {count-10} кодов"
                
                TelegramAPI.send_message(user_id, codes_text)
            except ValueError:
                TelegramAPI.send_message(
                    user_id,
                    "❌ Количество должно быть числом!"
                )
            return
    
    # Проверка на ответ админа
    if message.get('reply_to_message') and is_admin:
        reply_text = message.get('reply_to_message', {}).get('text', '')
        
        # Загрузка VPN
        if 'Загрузка VPN' in reply_text:
            lines = text.strip().split('\n')
            count = 0
            
            for line in lines:
                line = line.strip()
                if line and (line.startswith('http://') or line.startswith('https://')):
                    existing = db.fetch_one(
                        "SELECT * FROM vpn_links WHERE link = ?",
                        (line,)
                    )
                    
                    if not existing:
                        db.execute(
                            "INSERT INTO vpn_links (link) VALUES (?)",
                            (line,)
                        )
                        count += 1
            
            response_text = f"""
✅ <b>VPN загружены!</b>

Добавлено новых ссылок: <b>{count}</b>

📢 Уведомления отправлены пользователям!
            """
            
            TelegramAPI.send_message(user_id, response_text.strip())
            
            # Уведомления
            users = db.fetch_all("SELECT user_id FROM users WHERE notifications_enabled = 1")
            
            notify_text = f"""
🎉 <b>НОВЫЕ VPN ЗАГРУЖЕНЫ!</b>

✅ Добавлено {count} новых ссылок!

Спешите получить свежий VPN в меню!
            """
            
            for user in users:
                try:
                    TelegramAPI.send_message(
                        user['user_id'],
                        notify_text.strip(),
                        reply_markup=get_main_keyboard(user['user_id'] == ADMIN_ID)
                    )
                    time.sleep(0.05)
                except:
                    pass
            
            return
        
        # Рассылка
        if 'Рассылка' in reply_text:
            users = db.fetch_all("SELECT user_id FROM users")
            sent_count = 0
            
            for user in users:
                try:
                    TelegramAPI.send_message(
                        user['user_id'],
                        text,
                        reply_markup=get_main_keyboard(user['user_id'] == ADMIN_ID)
                    )
                    sent_count += 1
                    time.sleep(0.05)
                except:
                    pass
            
            response_text = f"""
✅ <b>Рассылка завершена!</b>

Отправлено сообщений: <b>{sent_count}</b>
            """
            
            TelegramAPI.send_message(user_id, response_text.strip())
            return
    
    # Проверка на промокод
    if message.get('reply_to_message'):
        reply_text = message.get('reply_to_message', {}).get('text', '')
        if 'промокод' in reply_text.lower():
            success, msg = use_promo_code(user_id, text.strip())
            TelegramAPI.send_message(user_id, msg)
            return

# ============================================================================
# ГЛАВНАЯ ПРОГРАММА
# ============================================================================

def process_update(update: dict):
    if 'message' in update:
        message = update['message']
        user_id = message['from']['id']
        
        db.execute(
            "UPDATE users SET is_online = 1, last_activity = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        
        if message.get('text'):
            if message['text'].startswith('/start'):
                handle_start_command(message)
            else:
                handle_text_message(message)
    
    elif 'callback_query' in update:
        callback_query = update['callback_query']
        user_id = callback_query['from']['id']
        
        db.execute(
            "UPDATE users SET is_online = 1, last_activity = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        
        handle_callback_query(callback_query)

def get_updates(timeout: int = 30):
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
            print(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print(f"✅ Бот {BOT_NAME} запущен!")
    print(f"🔑 Админ ID: {ADMIN_ID}")
    print(f"📢 Канал: @{CHANNEL_USERNAME}")
    print("\n🎧 Слушаю сообщения...\n")
    
    get_updates()
