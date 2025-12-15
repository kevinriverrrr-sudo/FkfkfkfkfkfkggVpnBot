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
CHANNEL_USERNAME = "DexterLogovo"  # только для информации в кнопке
SELLER_USERNAME = "DarkDalsho"     # кому писать по поводу покупки
BOT_USERNAME = "DexterFreeVpn"     # username бота без @
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
            [{"text": "🏆 Топ рефералов", "callback_data": "top_referrals"}],
            [{"text": "ℹ️ Информация", "callback_data": "info"}]
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

def generate_referral_code(user_id: int, length: int = 8) -> str:
    """Генерируем внутренний код, но пользователю даём именно ссылку на бота."""
    chars = string.ascii_letters + string.digits
    code = ''.join(random.choices(chars, k=length))
    existing = db.fetch_one("SELECT 1 FROM users WHERE referral_code = ?", (code,))
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


def add_referral(referrer_id: int, referred_user_id: int):
    if referrer_id == referred_user_id:
        return False

    # Уже есть реферер
    existing = db.fetch_one(
        "SELECT 1 FROM referrals WHERE referred_user_id = ?",
        (referred_user_id,)
    )
    if existing:
        return False

    # Записываем реферала
    db.execute(
        "INSERT INTO referrals (referrer_id, referred_user_id, bonus_applied) VALUES (?, ?, 1)",
        (referrer_id, referred_user_id)
    )

    # Минус один день кулдауна у рефера
    referrer = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (referrer_id,))
    if referrer['last_free_vpn_date']:
        last_date = datetime.fromisoformat(referrer['last_free_vpn_date'])
        new_date = last_date - timedelta(days=1)
        db.execute(
            "UPDATE users SET last_free_vpn_date = ? WHERE user_id = ?",
            (new_date.isoformat(), referrer_id)
        )

    # Уведомление рефереру
    if referrer['notifications_enabled']:
        txt = """🎉 <b>Новый реферал!</b>

Пользователь зашёл в бота по вашей ссылке.
✅ Ваш кулдаун уменьшен на 1 день.
"""
        TelegramAPI.send_message(referrer_id, txt.strip())

    return True


def get_user_profile_text(user_id: int) -> str:
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not user:
        return "Пользователь не найден"

    premium_status = "❌ Нет"
    if user['premium_until']:
        premium_date = datetime.fromisoformat(user['premium_until'])
        if premium_date > datetime.now():
            premium_status = f"✅ До {premium_date.strftime('%d.%m.%Y')}"
        else:
            premium_status = "❌ Истёк"

    if user['last_free_vpn_date']:
        last_vpn_date = datetime.fromisoformat(user['last_free_vpn_date'])
        next_vpn_date = last_vpn_date + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
        if next_vpn_date > datetime.now():
            delta = next_vpn_date - datetime.now()
            days_left = delta.days
            hours_left = delta.seconds // 3600
            cooldown_text = f"⏳ {days_left} д {hours_left} ч"
        else:
            cooldown_text = "✅ Доступно"
    else:
        cooldown_text = "✅ Доступно"

    referral_count = db.fetch_one(
        "SELECT COUNT(*) as c FROM referrals WHERE referrer_id = ?",
        (user_id,)
    )['c']

    referral_link = f"https://t.me/{BOT_USERNAME}?start={user['referral_code']}"

    text = f"""
<b>👤 Ваш профиль</b>

<b>ID:</b> {user['user_id']}
<b>Имя:</b> {user['first_name']} {user['last_name'] or ''}
<b>Username:</b> @{user['username'] or 'не указан'}

<b>📊 Статистика:</b>
• <b>Премиум:</b> {premium_status}
• <b>Бесплатный VPN:</b> {cooldown_text}
• <b>Рефералов привлечено:</b> {referral_count}

<b>🔗 Ваша реферальная ссылка:</b>
<code>{referral_link}</code>
"""
    return text.strip()


def get_statistics_text() -> str:
    total_users = db.fetch_one("SELECT COUNT(*) as c FROM users")['c']
    total_vpns = db.fetch_one("SELECT COUNT(*) as c FROM vpn_links WHERE is_active = 1")['c']
    total_given = db.fetch_one("SELECT SUM(given_count) as s FROM vpn_links")['s'] or 0
    today_given = db.fetch_one(
        "SELECT COUNT(*) as c FROM vpn_history WHERE date(received_date) = date('now')"
    )['c']
    month_given = db.fetch_one(
        "SELECT COUNT(*) as c FROM vpn_history WHERE date(received_date) >= date('now','-30 days')"
    )['c']

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


def get_top_referrals_text() -> str:
    rows = db.fetch_all(
        """
        SELECT u.user_id, u.first_name, u.username, COUNT(r.id) as ref_count
        FROM users u
        JOIN referrals r ON u.user_id = r.referrer_id
        GROUP BY u.user_id
        HAVING ref_count > 0
        ORDER BY ref_count DESC
        LIMIT 10
        """
    )
    if not rows:
        return "<b>🏆 Топ рефералов</b>\n\nПока никто не привёл друзей."

    text = "<b>🏆 Топ 10 рефералов</b>\n\n"
    for i, row in enumerate(rows, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = row['first_name'] or ''
        username = f"@{row['username']}" if row['username'] else ''
        text += f"{medal} {name} {username} — <b>{row['ref_count']}</b> реф.\n"
    return text.strip()


# ============================================================================
# ПРОМОКОДЫ
# ============================================================================

def generate_promo_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choices(chars, k=length))
    existing = db.fetch_one("SELECT 1 FROM promo_codes WHERE code = ?", (code,))
    if existing:
        return generate_promo_code(length)
    return code


def create_promo_codes(count: int, usage_limit: Optional[int] = None) -> List[str]:
    codes = []
    for _ in range(count):
        c = generate_promo_code()
        db.execute(
            "INSERT INTO promo_codes (code, usage_limit) VALUES (?, ?)",
            (c, usage_limit)
        )
        codes.append(c)
    return codes


def use_promo_code(user_id: int, code: str):
    code = code.upper().strip()
    promo = db.fetch_one(
        "SELECT * FROM promo_codes WHERE code = ? AND is_active = 1",
        (code,)
    )
    if not promo:
        return False, "❌ Промокод не найден или неактивен."

    if promo['usage_limit'] and promo['usage_count'] >= promo['usage_limit']:
        return False, "❌ Лимит активаций этого промокода исчерпан."

    used = db.fetch_one(
        "SELECT 1 FROM promo_usage WHERE user_id = ? AND promo_code = ?",
        (user_id, code)
    )
    if used:
        return False, "❌ Вы уже использовали этот промокод."

    # Обнуляем кулдаун
    db.execute(
        "UPDATE users SET last_free_vpn_date = NULL WHERE user_id = ?",
        (user_id,)
    )

    # Записываем использование
    db.execute(
        "INSERT INTO promo_usage (user_id, promo_code) VALUES (?, ?)",
        (user_id, code)
    )
    db.execute(
        "UPDATE promo_codes SET usage_count = usage_count + 1 WHERE code = ?",
        (code,)
    )

    return True, "✅ Промокод применён! Кулдаун обнулён, можете сразу получать VPN."


# ============================================================================
# ОБРАБОТЧИК /start С УЧЁТОМ РЕФЕРАЛКИ
# ============================================================================

def handle_start_command(message: dict):
    user_id = message['from']['id']
    username = message['from'].get('username', '')
    first_name = message['from'].get('first_name', '')
    last_name = message['from'].get('last_name', '')

    args = message.get('text', '').split()
    user = get_or_create_user(user_id, username, first_name, last_name)

    # Если пришли по реферальной ссылке вида /start <ref_code>
    if len(args) > 1:
        ref_code = args[1]
        referrer = db.fetch_one(
            "SELECT * FROM users WHERE referral_code = ?",
            (ref_code,)
        )
        if referrer and referrer['user_id'] != user_id:
            already_has_ref = db.fetch_one(
                "SELECT 1 FROM referrals WHERE referred_user_id = ?",
                (user_id,)
            )
            if not already_has_ref:
                db.execute(
                    "UPDATE users SET referrer_id = ? WHERE user_id = ?",
                    (referrer['user_id'], user_id)
                )
                add_referral(referrer['user_id'], user_id)

    is_admin = (user_id == ADMIN_ID)

    welcome_text = f"""
<b>🎉 Добро пожаловать в {BOT_USERNAME}!</b>

Это бот для раздачи бесплатных VPN.

<b>Что здесь есть:</b>
• 📥 Бесплатные VPN (1 раз в 3 недели)
• 🔗 Рефералка (минус 1 день за каждого друга)
• 🎁 Промокоды (обнуление кулдауна)
• 💳 Премиум доступ (3 тарифа)
• 📊 Статистика и 🏆 Топ рефералов

Нажмите кнопку ниже, чтобы начать.
"""
    TelegramAPI.send_message(
        user_id,
        welcome_text.strip(),
        reply_markup=get_main_keyboard(is_admin)
    )


# ============================================================================
# CALLBACK-ОБРАБОТЧИКИ
# ============================================================================

def handle_callback_query(callback_query: dict):
    user_id = callback_query['from']['id']
    data = callback_query['data']
    chat_id = callback_query['message']['chat']['id']
    message_id = callback_query['message']['message_id']
    is_admin = (user_id == ADMIN_ID)

    if data == "back_main":
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            "📱 <b>Главное меню</b>",
            reply_markup=get_main_keyboard(is_admin)
        )
        return

    # ---------- ПОЛУЧИТЬ VPN ----------
    if data == "get_vpn":
        user = get_or_create_user(user_id)

        # проверяем премиум
        has_premium = False
        if user['premium_until']:
            premium_until = datetime.fromisoformat(user['premium_until'])
            has_premium = premium_until > datetime.now()

        # кулдаун если нет премиума
        if not has_premium:
            if user['last_free_vpn_date']:
                last = datetime.fromisoformat(user['last_free_vpn_date'])
                next_date = last + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
                if next_date > datetime.now():
                    delta = next_date - datetime.now()
                    days_left = delta.days
                    hours_left = delta.seconds // 3600
                    txt = f"""
<b>⏳ Кулдаун активен</b>

До следующего бесплатного VPN:
<b>{days_left} дней {hours_left} часов</b>

<b>Что можно сделать:</b>
• Пригласить друзей (−1 день за каждого)
• Ввести промокод (обнуление кулдауна)
• Купить доступ
"""
                    TelegramAPI.edit_message(
                        chat_id,
                        message_id,
                        txt.strip(),
                        reply_markup={
                            "inline_keyboard": [
                                [{"text": "💳 Купить доступ", "callback_data": "buy_vpn"}],
                                [{"text": "🎁 Ввести промокод", "callback_data": "enter_promo"}],
                                [{"text": "⬅️ Назад", "callback_data": "back_main"}]
                            ]
                        }
                    )
                    return

        # выдаём VPN
        vpn = db.fetch_one(
            "SELECT * FROM vpn_links WHERE is_active = 1 ORDER BY RANDOM() LIMIT 1"
        )
        if not vpn:
            TelegramAPI.edit_message(
                chat_id,
                message_id,
                "❌ Сейчас нет доступных VPN. Подождите, пока админ загрузит новые.",
                reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
            )
            return

        if not has_premium:
            db.execute(
                "UPDATE users SET last_free_vpn_date = ? WHERE user_id = ?",
                (datetime.now().isoformat(), user_id)
            )

        db.execute(
            "INSERT INTO vpn_history (user_id, link) VALUES (?, ?)",
            (user_id, vpn['link'])
        )
        db.execute(
            "UPDATE vpn_links SET given_count = given_count + 1 WHERE id = ?",
            (vpn['id'],)
        )

        txt = f"""
<b>✅ Ваша VPN ссылка:</b>

<code>{vpn['link']}</code>

Скопируйте и импортируйте в своё VPN-приложение.
"""
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt.strip(),
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
        return

    # ---------- КУПИТЬ VPN ----------
    if data == "buy_vpn":
        txt = """
<b>💳 Купить доступ</b>

Выберите тариф ниже. Для оплаты пишите:
<b>@{SELLER}</b>
""".format(SELLER=SELLER_USERNAME)
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt.strip(),
            reply_markup=get_buy_keyboard()
        )
        return

    if data.startswith("buy_"):
        key = data.replace("buy_", "")
        if key not in TARIFFS:
            return
        t = TARIFFS[key]
        txt = f"""
<b>💳 Покупка тарифа</b>

Тариф: {t['name']}
Цена: {t['price']} руб
Срок: {t['duration_days']} дней

Для покупки напишите <b>@{SELLER}</b> и укажите:
• Ваш ID: <code>{uid}</code>
• Тариф: {t['name']}
""".format(SELLER=SELLER_USERNAME, uid=user_id)
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt.strip(),
            reply_markup={
                "inline_keyboard": [
                    [{"text": "💬 Написать @{SELLER}".format(SELLER=SELLER_USERNAME),
                      "url": f"https://t.me/{SELLER_USERNAME}"}],
                    [{"text": "⬅️ Назад", "callback_data": "buy_vpn"}]
                ]
            }
        )
        return

    # ---------- ПРОФИЛЬ / РЕФЕРАЛКИ / ПРОМОКОД ----------
    if data == "profile":
        txt = get_user_profile_text(user_id)
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt,
            reply_markup=get_profile_keyboard()
        )
        return

    if data == "referral_system":
        user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        ref_count = db.fetch_one(
            "SELECT COUNT(*) as c FROM referrals WHERE referrer_id = ?",
            (user_id,)
        )['c']
        referral_link = f"https://t.me/{BOT_USERNAME}?start={user['referral_code']}"
        txt = f"""
<b>🔗 Реферальная система</b>

1. Отправьте друзьям ссылку:
<code>{referral_link}</code>
2. Когда друг заходит в бота — вам минус 1 день кулдауна.

<b>Сейчас:</b>
• Рефералов: <b>{ref_count}</b>
• Сэкономлено дней: <b>{ref_count}</b>
"""
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt.strip(),
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "profile"}]]}
        )
        return

    if data == "enter_promo":
        txt = """
<b>🎁 Промокод</b>

Отправьте промокод одним сообщением.
"""
        TelegramAPI.send_message(
            user_id,
            txt.strip(),
            reply_markup={"force_reply": True}
        )
        return

    # ---------- СТАТИСТИКА / ТОП ----------
    if data == "statistics":
        txt = get_statistics_text()
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
        return

    if data == "top_referrals":
        txt = get_top_referrals_text()
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
        return

    # ---------- ИНФОРМАЦИЯ ----------
    if data == "info":
        txt = f"""
<b>ℹ️ Информация</b>

<b>Наш телеграм-канал:</b>
@{CHANNEL}
https://t.me/{CHANNEL}

<b>По вопросам покупки VPN писать:</b>
@{SELLER}
https://t.me/{SELLER}
""".format(CHANNEL=CHANNEL_USERNAME, SELLER=SELLER_USERNAME)
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt.strip(),
            reply_markup={
                "inline_keyboard": [
                    [{"text": "📢 Открыть канал", "url": f"https://t.me/{CHANNEL_USERNAME}"}],
                    [{"text": "💬 Написать @{SELLER}".format(SELLER=SELLER_USERNAME),
                      "url": f"https://t.me/{SELLER_USERNAME}"}],
                    [{"text": "⬅️ Назад", "callback_data": "back_main"}]
                ]
            }
        )
        return

    # ---------- АДМИН ПАНЕЛЬ И ДАЛЕЕ ----------
    if data == "admin" and is_admin:
        txt = "<b>⚙️ Админ-панель</b>\n\nВыберите действие:"
        TelegramAPI.edit_message(
            chat_id,
            message_id,
            txt,
            reply_markup=get_admin_keyboard()
        )
        return

    # остальной админ-функционал не меняем (загрузка VPN, промокоды, рассылка)


# ============================================================================
# ОБРАБОТЧИК ТЕКСТОВ (ПРОМОКОДЫ, АДМИН ОТВЕТЫ)
# ============================================================================

def handle_text_message(message: dict):
    user_id = message['from']['id']
    text = message.get('text', '')
    is_admin = (user_id == ADMIN_ID)

    # команды админа (create_promo, /admin и т.д.) — оставляем как в предыдущей версии
    if text.startswith('/') and is_admin:
        # здесь остаётся логика /admin, /create_promo и т.п. из прошлой версии
        # чтобы не раздувать ответ, предполагаем что этот код уже есть в файле
        return

    # reply на "промокод"
    if message.get('reply_to_message'):
        reply_txt = message['reply_to_message'].get('text', '').lower()
        if 'промокод' in reply_txt:
            ok, msg = use_promo_code(user_id, text)
            TelegramAPI.send_message(user_id, msg)
            return

    # reply админа на загрузку VPN/рассылку — также оставляем как в прошлой версии


# ============================================================================
# ЦИКЛ ОБНОВЛЕНИЙ
# ============================================================================

def process_update(update: dict):
    if 'message' in update:
        msg = update['message']
        user_id = msg['from']['id']
        db.execute(
            "UPDATE users SET is_online = 1, last_activity = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        if 'text' in msg:
            if msg['text'].startswith('/start'):
                handle_start_command(msg)
            else:
                handle_text_message(msg)
    elif 'callback_query' in update:
        cb = update['callback_query']
        user_id = cb['from']['id']
        db.execute(
            "UPDATE users SET is_online = 1, last_activity = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        handle_callback_query(cb)


def get_updates(timeout: int = 30):
    offset = 0
    url = f"{BASE_URL}/getUpdates"
    while True:
        try:
            resp = requests.post(url, json={"offset": offset, "timeout": timeout}, timeout=timeout + 5).json()
            if resp.get('ok'):
                for upd in resp.get('result', []):
                    offset = upd['update_id'] + 1
                    process_update(upd)
        except Exception as e:
            print('Ошибка:', e)
            time.sleep(5)


if __name__ == "__main__":
    print(f"✅ Бот {BOT_USERNAME} запущен")
    print(f"🔑 Админ ID: {ADMIN_ID}")
    print(f"📢 Канал для инфо: @{CHANNEL_USERNAME}")
    print(f"💬 Продавец: @{SELLER_USERNAME}")
    print("\n🎧 Слушаю обновления...\n")
    get_updates()
