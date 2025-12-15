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
CHANNEL_ID = -1001234567890
CHANNEL_USERNAME = "DarkDalsho"
BOT_NAME = "DexterFreeVpn"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Параметры системы
FREE_VPN_COOLDOWN_DAYS = 21  # 3 недели
VPN_PER_DAY = [1, 2]  # 1-2 ссылки в день для раздачи

# Тарифы премиума (для обхода кулдауна)
TARIFFS = {
    "7days": {"price": 30, "duration_days": 7, "name": "7 дней"},
    "30days": {"price": 50, "duration_days": 30, "name": "30 дней"},
    "90days": {"price": 120, "duration_days": 90, "name": "90 дней"},
    "180days": {"price": 200, "duration_days": 180, "name": "180 дней"},
    "365days": {"price": 300, "duration_days": 365, "name": "1 год"}
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
                link TEXT NOT NULL,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                given_count INTEGER DEFAULT 0,
                expiry_date TIMESTAMP
            )
        ''')

        # Таблица истории получения VPN
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vpn_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                link TEXT NOT NULL,
                received_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
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
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')

        # Логи админа
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

def get_main_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📥 Получить VPN", "callback_data": "get_vpn"}],
            [{"text": "💳 Купить доступ", "callback_data": "buy_vpn"}],
            [{"text": "⚙️ Профиль", "callback_data": "profile"}],
            [{"text": "📢 Свежие VPN", "callback_data": "latest_vpn"}]
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
            [{"text": "📥 Загрузить VPN ссылки", "callback_data": "admin_add_vpn"}],
            [{"text": "📋 Список VPN", "callback_data": "admin_list_vpn"}],
            [{"text": "📊 Статистика", "callback_data": "admin_stats"}],
            [{"text": "📢 Рассылка", "callback_data": "admin_broadcast"}],
            [{"text": "⬅️ Назад", "callback_data": "back_main"}]
        ]
    }

# ============================================================================
# ПОЛЬЗОВАТЕЛЬСКИЕ ФУНКЦИИ
# ============================================================================

def get_or_create_user(user_id: int, username: str = "", first_name: str = "", last_name: str = ""):
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    if not user:
        db.execute(
            "INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, last_name)
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

def get_user_profile_text(user_id: int):
    user = db.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    
    if not user:
        return "Пользователь не найден"
    
    # Проверка премиума
    premium_status = "❌ Нет"
    if user['premium_until']:
        premium_date = datetime.fromisoformat(user['premium_until'])
        if premium_date > datetime.now():
            premium_status = f"✅ До {premium_date.strftime('%d.%m.%Y')}"
        else:
            premium_status = "❌ Истек"
    
    # Проверка кулдауна
    if user['last_free_vpn_date']:
        last_vpn_date = datetime.fromisoformat(user['last_free_vpn_date'])
        next_vpn_date = last_vpn_date + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
        
        if next_vpn_date > datetime.now():
            days_left = (next_vpn_date - datetime.now()).days
            hours_left = ((next_vpn_date - datetime.now()).seconds // 3600)
            days_left_text = f"⏳ {days_left} д {hours_left} ч"
        else:
            days_left_text = "✅ Доступно"
    else:
        days_left_text = "✅ Доступно"
    
    text = f"""
<b>👤 Ваш профиль</b>

<b>ID:</b> {user['user_id']}
<b>Имя:</b> {user['first_name']} {user['last_name'] or ''}
<b>Юзернейм:</b> @{user['username']}

<b>📊 Статистика:</b>
• <b>Присоединился:</b> {datetime.fromisoformat(user['joined_date']).strftime('%d.%m.%Y')}
• <b>Премиум статус:</b> {premium_status}
• <b>Бесплатный VPN:</b> {days_left_text}
    """
    return text.strip()

# ============================================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================================

def handle_start_command(message: dict):
    user_id = message['from']['id']
    username = message['from'].get('username', '')
    first_name = message['from'].get('first_name', '')
    last_name = message['from'].get('last_name', '')
    
    get_or_create_user(user_id, username, first_name, last_name)
    
    welcome_text = f"""
<b>🎉 Добро пожаловать в {BOT_NAME}!</b>

Это бот для раздачи бесплатных VPN ссылок!

<b>📋 Возможности:</b>
✅ Получайте бесплатные VPN ссылки (1 раз в 3 недели)
✅ Купите премиум для дополнительных VPN
✅ Следите за статистикой в профиле
✅ Получайте уведомления о новых VPN

<b>📢 Подпишитесь на канал:</b> @{CHANNEL_USERNAME}

Выберите действие ниже:
    """
    
    TelegramAPI.send_message(user_id, welcome_text.strip(), reply_markup=get_main_keyboard())

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
            "📱 <b>Главное меню</b>",
            reply_markup=get_main_keyboard()
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
        
        # Проверка кулдауна (если нет премиума)
        if not user['premium_until'] or datetime.fromisoformat(user['premium_until']) < datetime.now():
            if user['last_free_vpn_date']:
                last_vpn_date = datetime.fromisoformat(user['last_free_vpn_date'])
                next_vpn_date = last_vpn_date + timedelta(days=FREE_VPN_COOLDOWN_DAYS)
                
                if next_vpn_date > datetime.now():
                    days_left = (next_vpn_date - datetime.now()).days
                    hours_left = ((next_vpn_date - datetime.now()).seconds // 3600)
                    
                    cooldown_text = f"""
<b>⏳ Кулдаун VPN</b>

До следующего бесплатного VPN осталось:
<b>{days_left} дней {hours_left} часов</b>

💡 <b>Опции:</b>
• Подождите до указанного времени
• Купите доступ в "Купить доступ"
                    """
                    
                    TelegramAPI.edit_message(
                        chat_id, message_id,
                        cooldown_text.strip(),
                        reply_markup={
                            "inline_keyboard": [
                                [{"text": "💳 Купить доступ", "callback_data": "buy_vpn"}],
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
        
        # Обновить дату последнего получения
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
<b>✅ Вот ваша VPN ссылка!</b>

<code>{vpn_link['link']}</code>

<b>📋 Инструкция:</b>
1. Скопируйте ссылку
2. Откройте приложение VPN
3. Импортируйте конфиг
4. Подключитесь!

⏰ Следующую ссылку сможете получить через 3 недели.
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

📝 <b>Способ оплаты:</b>
Свяжитесь с @{CHANNEL_USERNAME} для оформления покупки.

Передайте администратору:
• Ваш ID: <code>{user_id}</code>
• Тариф: {tariff_info['name']}
• Цена: {tariff_info['price']} руб
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
        user = get_or_create_user(user_id)
        profile_text = get_user_profile_text(user_id)
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            profile_text,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
    
    # ========== СВЕЖИЕ VPN ==========
    
    elif callback_data == "latest_vpn":
        vpn_links = db.fetch_all(
            "SELECT * FROM vpn_links WHERE is_active = 1 ORDER BY added_date DESC LIMIT 5"
        )
        
        if not vpn_links:
            latest_text = "❌ Свежих VPN нет. Следите за обновлениями!"
        else:
            latest_text = "<b>📥 5 Последних VPN:</b>\n\n"
            for i, vpn in enumerate(vpn_links, 1):
                added = datetime.fromisoformat(vpn['added_date']).strftime('%d.%m %H:%M')
                latest_text += f"{i}. <code>{vpn['link']}</code>\n   📅 {added}\n\n"
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            latest_text,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "back_main"}]]}
        )
    
    # ========== АДМИНИСТРАТОР ==========
    
    elif callback_data == "admin" and is_admin:
        admin_text = "<b>⚙️ Администраторская панель</b>"
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

Либо отправьте одну ссылку в сообщении.
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
                list_text += f"{i}. <code>{vpn['link']}</code>\n   Выдано: {vpn['given_count']} | ID: {vpn['id']}\n\n"
        
        TelegramAPI.edit_message(
            chat_id, message_id,
            list_text,
            reply_markup={"inline_keyboard": [[{"text": "⬅️ Назад", "callback_data": "admin"}]]}
        )
    
    elif callback_data == "admin_stats" and is_admin:
        total_users = db.fetch_one("SELECT COUNT(*) as count FROM users")['count']
        total_vpns = db.fetch_one("SELECT COUNT(*) as count FROM vpn_links WHERE is_active = 1")['count']
        today_users = db.fetch_one(
            "SELECT COUNT(*) as count FROM users WHERE date(joined_date) = date('now')"
        )['count']
        
        stats_text = f"""
<b>📊 Статистика бота</b>

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
    
    # Проверка на команды администратора
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
    
    # Проверка на ответ администратора (загрузка VPN или рассылка)
    if message.get('reply_to_message') and is_admin:
        reply_text = message.get('reply_to_message', {}).get('text', '')
        
        # Загрузка VPN
        if 'Загрузка VPN' in reply_text:
            lines = text.strip().split('\n')
            count = 0
            
            for line in lines:
                line = line.strip()
                if line and (line.startswith('http://') or line.startswith('https://')):
                    # Проверка что ссылка уже не в БД
                    existing = db.fetch_one(
                        "SELECT * FROM vpn_links WHERE link = ?",
                        (line,)
                    )
                    
                    if not existing:
                        db.execute(
                            "INSERT INTO vpn_links (link, expiry_date) VALUES (?, ?)",
                            (line, (datetime.now() + timedelta(days=90)).isoformat())
                        )
                        count += 1
            
            response_text = f"""
✅ <b>VPN загружены!</b>

Добавлено новых ссылок: <b>{count}</b>

📢 Уведомления отправлены пользователям!
            """
            
            TelegramAPI.send_message(user_id, response_text.strip())
            
            # Отправка уведомлений пользователям
            users = db.fetch_all("SELECT user_id, notifications_enabled FROM users WHERE notifications_enabled = 1")
            
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
                        reply_markup=get_main_keyboard()
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
                        reply_markup=get_main_keyboard()
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

# ============================================================================
# ГЛАВНАЯ ПРОГРАММА
# ============================================================================

def process_update(update: dict):
    if 'message' in update:
        message = update['message']
        user_id = message['from']['id']
        
        # Обновить статус онлайна
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
        
        # Обновить статус онлайна
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

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    print(f"✅ Бот {BOT_NAME} запущен!")
    print(f"🔑 Админ ID: {ADMIN_ID}")
    print(f"📢 Канал: @{CHANNEL_USERNAME}")
    print("\n🎧 Слушаю сообщения...\n")
    
    get_updates()
