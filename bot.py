import os
import asyncio
import datetime
import logging
import requests
import httpx
import openai
import uvicorn
import sqlite3
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters, ConversationHandler
)

load_dotenv()

# ================== Ключі та параметри ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")
CHANNEL_CHAT_ID = int(os.getenv("CHANNEL_CHAT_ID", "0"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK")

# Приклад тарифів — заміни на свої
TARIFFS = {
    "month": {"duration_days": 30, "amount": 10, "labels": {"uk": "Місячна", "ru": "Месячная", "en": "Monthly"}},
    "year": {"duration_days": 365, "amount": 100, "labels": {"uk": "Річна", "ru": "Годовая", "en": "Yearly"}},
}

openai.api_key = OPENAI_API_KEY
logging.basicConfig(level=logging.INFO)

telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
fastapi_app = FastAPI()

# Підключення до БД для GPT лімітів
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS gpt_usage (
    user_id INTEGER,
    date TEXT,
    prompt TEXT,
    tokens INTEGER DEFAULT 0
)
""")
conn.commit()

# ================== Імпорт своїх функцій для роботи з користувачами ==================
from db import add_or_update_user, get_user_profile, get_all_users, remove_user

# ================== Тексти і мови ==================
LANGUAGES = {"uk": "Українська", "ru": "Русский", "en": "English"}

TEXT = {
    "choose_lang": {
        "uk": "Оберіть мову:", "ru": "Выберите язык:", "en": "Choose your language:"
    },
    "main_menu": {
        "uk": "Вітаю, {name}!\nОберіть:", "ru": "Привет, {name}!\nВыберите:", "en": "Welcome, {name}!\nChoose:"
    },
    "buttons": {
        "access": {"uk": "📊 Мій доступ", "ru": "📊 Мой доступ", "en": "📊 My Access"},
        "subscribe": {"uk": "🔁 Продовжити підписку", "ru": "🔁 Продлить подписку", "en": "🔁 Renew Subscription"},
        "freetrial": {"uk": "🎁 Безкоштовно на 1 годину", "ru": "🎁 Бесплатно на 1 час", "en": "🎁 Free 1-hour trial"},
        "news": {"uk": "📰 Новини", "ru": "📰 Новости", "en": "📰 News"},
        "commands": {"uk": "📌 Команди", "ru": "📌 Команды", "en": "📌 Commands"},
        "gpt": {"uk": "🧠 GPT", "ru": "🧠 GPT", "en": "🧠 GPT"},
        "weather": {"uk": "☀️ Погода", "ru": "☀️ Погода", "en": "☀️ Weather"},
        "prices": {"uk": "💱 Курси валют", "ru": "💱 Курсы валют", "en": "💱 Prices"},
        "admin": {"uk": "⚙️ Адмін", "ru": "⚙️ Админ", "en": "⚙️ Admin"},
        "back": {"uk": "⬅️ Назад", "ru": "⬅️ Назад", "en": "⬅️ Back"},
        "cancel": {"uk": "❌ Скасувати", "ru": "❌ Отмена", "en": "❌ Cancel"},
    },
    "commands_list": {
        "uk": "/start — стартове меню\n/myaccess — мій доступ\n/help — команди\n/admin — адмін-панель\n/ask — GPT\n/testask — тестова команда (адмін)\n/price — ціни\n/predict — прогноз по монеті\n/broadcast — розсилка (admin)",
        "ru": "/start — главное меню\n/myaccess — мой доступ\n/help — команды\n/admin — админ-панель\n/ask — GPT\n/testask — тест для админа\n/price — цены\n/predict — прогноз по монете\n/broadcast — рассылка",
        "en": "/start — main menu\n/myaccess — my access\n/help — commands\n/admin — admin panel\n/ask — GPT\n/testask — admin test\n/price — prices\n/predict — coin forecast\n/broadcast — broadcast"
    },
    "choose_tariff": {"uk": "Оберіть тариф:", "ru": "Выберите тариф:", "en": "Choose tariff:"},
    "pay_success": {"uk": "✅ Доступ активовано!", "ru": "✅ Доступ активирован!", "en": "✅ Access activated!"},
    "not_subscribed": {"uk": "❌ Не підписані. Підпишіться: ", "ru": "❌ Не подписаны. Подпишитесь: ", "en": "❌ Not subscribed. Subscribe: "},
    "access_status": {"uk": "✅ Доступ активний, залишилось {days} днів", "ru": "✅ Доступ активен, осталось {days} дней", "en": "✅ Access active, {days} days left"},
    "no_access": {"uk": "❌ Немає активної підписки.", "ru": "❌ Нет подписки.", "en": "❌ No active subscription."},
    "predict_usage": {"uk": "📊 Напишіть /predict BTCUSDT", "ru": "📊 Напишите /predict BTCUSDT", "en": "📊 Write /predict BTCUSDT"},
    "predict_error": {"uk": "❌ Помилка прогнозу.", "ru": "❌ Ошибка прогноза.", "en": "❌ Forecast error."},
    "gpt_limit": {"uk": "⚠️ Вичерпано 5 запитів на сьогодні.", "ru": "⚠️ Лимит 5 запросов исчерпан.", "en": "⚠️ You used 5 GPT requests today."},
    "news_not_implemented": {"uk": "📰 Останні новини поки що не реалізовані.", "ru": "📰 Последние новости пока не реализованы.", "en": "📰 Latest news not implemented yet."},
    "weather_prompt": {"uk": "Введіть назву міста для погоди:", "ru": "Введите название города для погоды:", "en": "Enter city name for weather:"},
    "weather_error": {"uk": "❌ Не вдалося отримати погоду.", "ru": "❌ Не удалось получить погоду.", "en": "❌ Could not get weather."},
    "broadcast_usage": {"uk": "Введіть текст для розсилки:", "ru": "Введите текст для рассылки:", "en": "Enter text for broadcast:"},
    "broadcast_sent": {"uk": "✅ Розсилка відправлена.", "ru": "✅ Рассылка отправлена.", "en": "✅ Broadcast sent."},
    "cancelled": {"uk": "❌ Скасовано.", "ru": "❌ Отменено.", "en": "❌ Cancelled."},
    "gpt_prompt": {"uk": "🧠 Введіть ваш запит до GPT:", "ru": "🧠 Введите ваш запрос к GPT:", "en": "🧠 Enter your GPT query:"},
    "processing": {"uk": "⏳ Обробка запиту...", "ru": "⏳ Обработка запроса...", "en": "⏳ Processing request..."},
    "gpt_error": {"uk": "❌ Помилка обробки запиту.", "ru": "❌ Ошибка обработки запроса.", "en": "❌ Processing error."},
}

user_lang = {}
def lang(uid): return user_lang.get(uid, "uk")
def tr(uid, key): return TEXT[key][lang(uid)]

# ================== GPT Usage ==================
def can_use_gpt(uid):
    today = datetime.date.today().isoformat()
    cursor.execute("SELECT COUNT(*) FROM gpt_usage WHERE user_id=? AND date=?", (uid, today))
    count = cursor.fetchone()[0]
    return count < 5

def log_gpt_usage(uid, prompt, tokens=0):
    today = datetime.date.today().isoformat()
    cursor.execute("INSERT INTO gpt_usage (user_id, date, prompt, tokens) VALUES (?, ?, ?, ?)", (uid, today, prompt, tokens))
    conn.commit()

# ================== Conversation states ==================
ASK_GPT = 1
ASK_WEATHER = 2
BROADCAST = 3

# ================== Основні хендлери ==================

@fastapi_app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    if "payload" in data:
        uid, key = data["payload"].split(":")
        add_or_update_user(int(uid), TARIFFS[key]["duration_days"])
        return {"ok": True}
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(name, callback_data=f"lang:{code}")] for code, name in LANGUAGES.items()]
    await update.message.reply_text(TEXT["choose_lang"]["uk"], reply_markup=InlineKeyboardMarkup(kb))

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(TEXT["commands_list"][lang(uid)])

async def myaccess_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == OWNER_ID:
        await update.message.reply_text(tr(uid, "access_status").format(days=9999) + " (Адмін, безліміт)")
        return
    row = get_user_profile(uid)
    if row:
        days = (datetime.datetime.fromisoformat(row[1]) - datetime.datetime.now()).days
        if days < 0:
            await update.message.reply_text(tr(uid, "no_access"))
        else:
            await update.message.reply_text(tr(uid, "access_status").format(days=days))
    else:
        await update.message.reply_text(tr(uid, "no_access"))

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        return await update.message.reply_text("⛔ Access denied.")
    users = get_all_users()
    now = datetime.datetime.now()
    active = sum(1 for _, e in users if datetime.datetime.fromisoformat(e) > now)
    inactive = len(users) - active
    msg = f"👥 Користувачів: {len(users)}\n✅ Активних: {active}\n❌ Неактивних: {inactive}"
    await update.message.reply_text(msg)

# ================== Menu Handlers ==================

async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    code = lang(uid)
    kb = [
        [InlineKeyboardButton(TEXT["buttons"]["access"][code], callback_data="access"),
         InlineKeyboardButton(TEXT["buttons"]["subscribe"][code], callback_data="subscribe")],
        [InlineKeyboardButton(TEXT["buttons"]["freetrial"][code], callback_data="freetrial"),
         InlineKeyboardButton(TEXT["buttons"]["news"][code], callback_data="news")],
        [InlineKeyboardButton(TEXT["buttons"]["gpt"][code], callback_data="gpt"),
         InlineKeyboardButton(TEXT["buttons"]["weather"][code], callback_data="weather")],
        [InlineKeyboardButton(TEXT["buttons"]["prices"][code], callback_data="prices")],
    ]
    if uid == OWNER_ID:
        kb.append([InlineKeyboardButton(TEXT["buttons"]["admin"][code], callback_data="admin")])
    await update.message.reply_text(TEXT["main_menu"][code].format(name=update.effective_user.first_name), reply_markup=InlineKeyboardMarkup(kb))

# ================== Callback Query Handler ==================

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data
    code = lang(uid)

    if data.startswith("lang:"):
        code = data.split(":")[1]
        user_lang[uid] = code
        # Показати головне меню
        await q.edit_message_text(TEXT["main_menu"][code].format(name=q.from_user.first_name), reply_markup=main_menu_kb(code, uid))

    elif data == "access":
        row = get_user_profile(uid)
        if uid == OWNER_ID:
            await q.edit_message_text(tr(uid, "access_status").format(days=9999) + " (Адмін, безліміт)")
            return
        if row:
            days = (datetime.datetime.fromisoformat(row[1]) - datetime.datetime.now()).days
            if days < 0:
                await q.edit_message_text(tr(uid, "no_access"))
            else:
                await q.edit_message_text(tr(uid, "access_status").format(days=days))
        else:
            await q.edit_message_text(tr(uid, "no_access"))

    elif data == "subscribe":
        kb = [[InlineKeyboardButton(TARIFFS[k]["labels"][code], callback_data=f"tariff:{k}")] for k in TARIFFS]
        kb.append([InlineKeyboardButton(TEXT["buttons"]["back"][code], callback_data="back_to_main")])
        await q.edit_message_text(tr(uid, "choose_tariff"), reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("tariff:"):
        tariff_key = data.split(":")[1]
        t = TARIFFS[tariff_key]
        resp = requests.post("https://pay.crypt.bot/api/createInvoice", json={
            "asset": "USDT", "amount": t["amount"],
            "description": f"{t['duration_days']} days",
            "paid_btn_name": "openBot",
            "paid_btn_url": f"https://t.me/{BOT_USERNAME}",
            "payload": f"{uid}:{tariff_key}"
        }, headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN})
        rj = resp.json()
        if rj.get("ok"):
            url = rj["result"]["pay_url"]
            kb = [[InlineKeyboardButton("✅ Я оплатив", callback_data="check_payment")],
                  [InlineKeyboardButton(TEXT["buttons"]["back"][code], callback_data="back_to_main")]]
            await q.edit_message_text(f"💳 Оплатіть тут:\n{url}", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.edit_message_text("❌ Помилка створення рахунку.")

    elif data == "check_payment":
        try:
            # Перевіряємо чи користувач є учасником каналу (для прикладу)
            m = await ctx.bot.get_chat_member(CHANNEL_CHAT_ID, uid)
            if m.status in ["member", "administrator", "creator"]:
                # Продовжуємо підписку
                add_or_update_user(uid, TARIFFS["month"]["duration_days"])  # або можна зберегти тариф з user_data
                await q.edit_message_text(tr(uid, "pay_success"))
            else:
                raise Exception()
        except:
            await q.edit_message_text(tr(uid, "not_subscribed") + CHANNEL_LINK)

    elif data == "freetrial":
        add_or_update_user(uid, 0.0417)  # 1 година
        await q.edit_message_text("✅ Безкоштовний доступ на 1 годину активовано!")

    elif data == "news":
        # Отримуємо останні новини через CryptoPanic API
        try:
            async with httpx.AsyncClient() as cli:
                r = await cli.get("https://cryptopanic.com/api/developer/v2/posts/", params={"auth_token": CRYPTOPANIC_API_KEY, "public": "true"})
                posts = r.json().get("results", [])[:5]
            if posts:
                msg = "📰 Останні новини:\n" + "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
            else:
                msg = tr(uid, "news_not_implemented")
        except Exception as e:
            logging.error(e)
            msg = tr(uid, "news_not_implemented")
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXT["buttons"]["back"][code], callback_data="back_to_main")]]))

    elif data == "weather":
        await q.edit_message_text(tr(uid, "weather_prompt"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXT["buttons"]["cancel"][code], callback_data="back_to_main")]]))
        ctx.user_data["awaiting_weather"] = True

    elif data == "prices":
        try:
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=[\"BTCUSDT\",\"ETHUSDT\"]")
            data = r.json()
            msg = "\n".join(f"{d['symbol']}: {d['price']}" for d in data)
        except:
            msg = "❌ Помилка отримання курсу."
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXT["buttons"]["back"][code], callback_data="back_to_main")]]))

    elif data == "admin":
        if uid != OWNER_ID:
            await q.edit_message_text("⛔ Access denied.")
            return
        kb = [
            [InlineKeyboardButton("/broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton(TEXT["buttons"]["back"][code], callback_data="back_to_main")]
        ]
        await q.edit_message_text("Адмін меню:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_broadcast":
        if uid != OWNER_ID:
            await q.edit_message_text("⛔ Access denied.")
            return
        await q.edit_message_text(tr(uid, "broadcast_usage"))
        ctx.user_data["broadcasting"] = True

    elif data == "back_to_main":
        await q.edit_message_text(TEXT["main_menu"][code].format(name=q.from_user.first_name), reply_markup=main_menu_kb(code, uid))

    elif data == "gpt":
        if uid != OWNER_ID and not get_user_profile(uid):
            await q.edit_message_text(tr(uid, "no_access"))
            return
        if uid != OWNER_ID and not can_use_gpt(uid):
            await q.edit_message_text(tr(uid, "gpt_limit"))
            return
        await q.edit_message_text(tr(uid, "gpt_prompt"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(TEXT["buttons"]["cancel"][code], callback_data="back_to_main")]]))
        ctx.user_data["awaiting_gpt"] = True

# ================== Функція побудови головного меню (для редагування) ==================
def main_menu_kb(code, uid):
    kb = [
        [InlineKeyboardButton(TEXT["buttons"]["access"][code], callback_data="access"),
         InlineKeyboardButton(TEXT["buttons"]["subscribe"][code], callback_data="subscribe")],
        [InlineKeyboardButton(TEXT["buttons"]["freetrial"][code], callback_data="freetrial"),
         InlineKeyboardButton(TEXT["buttons"]["news"][code], callback_data="news")],
        [InlineKeyboardButton(TEXT["buttons"]["gpt"][code], callback_data="gpt"),
         InlineKeyboardButton(TEXT["buttons"]["weather"][code], callback_data="weather")],
        [InlineKeyboardButton(TEXT["buttons"]["prices"][code], callback_data="prices")],
    ]
    if uid == OWNER_ID:
        kb.append([InlineKeyboardButton(TEXT["buttons"]["admin"][code], callback_data="admin")])
    return InlineKeyboardMarkup(kb)

# ================== Обробка повідомлень (текст) ==================

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    code = lang(uid)

    # Скасувати запити
    if text.lower() in [TEXT["buttons"]["cancel"][code].lower(), "cancel", "скасувати", "отмена"]:
        ctx.user_data.clear()
        await update.message.reply_text(tr(uid, "cancelled"), reply_markup=main_menu_kb(code, uid))
        return

    # Якщо чекаємо на GPT запит
    if ctx.user_data.get("awaiting_gpt"):
        await update.message.reply_text(tr(uid, "processing"))
        try:
            res = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": text}]
            )
            answer = res.choices[0].message.content
            log_gpt_usage(uid, text)
            await update.message.reply_text(answer[:4000], reply_markup=main_menu_kb(code, uid))
        except Exception as e:
            logging.error(e)
            await update.message.reply_text(tr(uid, "gpt_error"), reply_markup=main_menu_kb(code, uid))
        ctx.user_data.pop("awaiting_gpt", None)
        return

    # Якщо чекаємо на погоду
    if ctx.user_data.get("awaiting_weather"):
        city = text
        await update.message.reply_text(tr(uid, "processing"))
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang={code}"
            r = requests.get(url).json()
            if r.get("cod") != 200:
                raise Exception()
            weather_desc = r["weather"][0]["description"].capitalize()
            temp = r["main"]["temp"]
            humidity = r["main"]["humidity"]
            wind = r["wind"]["speed"]
            msg = f"Погода в {city}:\n{weather_desc}\n🌡 Температура: {temp}°C\n💧 Вологість: {humidity}%\n🌬 Вітер: {wind} м/с"
        except:
            msg = tr(uid, "weather_error")
        await update.message.reply_text(msg, reply_markup=main_menu_kb(code, uid))
        ctx.user_data.pop("awaiting_weather", None)
        return

    # Якщо чекаємо на текст для розсилки (адмін)
    if ctx.user_data.get("broadcasting"):
        if uid != OWNER_ID:
            await update.message.reply_text("⛔ Access denied.")
            ctx.user_data.pop("broadcasting", None)
            return
        text_to_send = text
        users = get_all_users()
        count = 0
        for user_id, _ in users:
            try:
                await telegram_app.bot.send_message(user_id, text_to_send)
                count += 1
            except:
                pass
        await update.message.reply_text(f"{tr(uid, 'broadcast_sent')} {count} користувачам.", reply_markup=main_menu_kb(code, uid))
        ctx.user_data.pop("broadcasting", None)
        return

    # Якщо текст не розпізнано — показати головне меню
    await update.message.reply_text(TEXT["main_menu"][code].format(name=update.effective_user.first_name), reply_markup=main_menu_kb(code, uid))


# ================== Команди ==================

async def price_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    code = lang(uid)
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=[\"BTCUSDT\",\"ETHUSDT\"]")
        data = r.json()
        msg = "\n".join(f"{d['symbol']}: {d['price']}" for d in data)
    except:
        msg = "❌ Помилка отримання курсу."
    await update.message.reply_text(msg, reply_markup=main_menu_kb(code, uid))

async def predict_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    code = lang(uid)
    if uid != OWNER_ID and not get_user_profile(uid):
        await update.message.reply_text(tr(uid, "no_access"))
        return
    if not ctx.args:
        await update.message.reply_text(tr(uid, "predict_usage"))
        return
    symbol = ctx.args[0].upper()
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}")
        d = r.json()
        prompt = f"Прогноз по {symbol}:\nЦіна: {d['lastPrice']}, Зміна: {d['priceChangePercent']}%, Обʼєм: {d['volume']}."
        res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        await update.message.reply_text(res.choices[0].message.content[:4000], reply_markup=main_menu_kb(code, uid))
    except Exception as e:
        logging.error(e)
        await update.message.reply_text(tr(uid, "predict_error"), reply_markup=main_menu_kb(code, uid))

async def testask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("⛔ Лише для адміна.")
        return
    q = " ".join(ctx.args) or "Hello!"
    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": q}]
        )
        await update.message.reply_text(res.choices[0].message.content[:4000])
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("❌ Помилка.")

# ================== Перевірка підписки щогодини ==================

async def check_expiry(_):
    now = datetime.datetime.now()
    for uid, exp in get_all_users():
        dt = datetime.datetime.fromisoformat(exp)
        if (dt - now).days == 1:
            try:
                await telegram_app.bot.send_message(uid, "⏳ Ваша підписка скоро закінчиться, продовжіть.")
            except:
                pass

# ================== Додавання хендлерів ==================

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_cmd))
telegram_app.add_handler(CommandHandler("myaccess", myaccess_cmd))
telegram_app.add_handler(CommandHandler("admin", admin_cmd))
telegram_app.add_handler(CommandHandler("price", price_cmd))
telegram_app.add_handler(CommandHandler("predict", predict_cmd))
telegram_app.add_handler(CommandHandler("testask", testask_cmd))

telegram_app.add_handler(CallbackQueryHandler(handle_cb))
telegram_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

# ================== Запуск FastAPI разом з ботом ==================

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    import threading

    def run_fastapi():
        uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

    threading.Thread(target=run_fastapi).start()
    telegram_app.run_polling()

