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
        kb = [
            [InlineKeyboardButton("✅ Я оплатив", callback_data="check_payment")],
            [InlineKeyboardButton(TEXT["buttons"]["back"][lang(uid)], callback_data="back_to_main")]
        ]
        await q.edit_message_text(f"💳 Оплатіть тут:\n{url}", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await q.edit_message_text("❌ Помилка створення рахунку.")

elif data == "check_payment":
    try:
        # Перевіряємо чи користувач є учасником каналу
        m = await ctx.bot.get_chat_member(CHANNEL_CHAT_ID, uid)
        if m.status in ["member", "administrator", "creator"]:
            # Продовжуємо підписку
            add_or_update_user(uid, TARIFFS["month"]["duration_days"])  # або зберегти тариф з user_data
            await q.edit_message_text(tr(uid, "pay_success"))
        else:
            raise Exception()
    except Exception:
        await q.edit_message_text(tr(uid, "not_subscribed") + CHANNEL_LINK)


    else:
        await q.edit_message_text("❌ Помилка створення рахунку.")

import logging
import sqlite3
import datetime
import requests
import httpx
import asyncio
import threading
import matplotlib.pyplot as plt
from io import BytesIO
from PIL import Image
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, Text
from aiogram.enums import ParseMode
from aiogram.utils.markdown import hbold
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
import openai
import uvicorn
import secrets
import stripe
import os
from dotenv import load_dotenv

# ================== .env ==================
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_CHAT_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")
OWNER_ID = int(os.getenv("OWNER_ID"))
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "sk_test_...your_default")

stripe.api_key = STRIPE_API_KEY
openai.api_key = OPENAI_API_KEY

bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()
fastapi_app = FastAPI()

# ================== SQLite ==================

conn = sqlite3.connect("bot.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    usage INTEGER DEFAULT 0,
    expires TEXT,
    referrals INTEGER DEFAULT 0,
    coins TEXT DEFAULT "BTC,ETH",
    referred_by INTEGER
)
""")
c.execute("CREATE TABLE IF NOT EXISTS gpt_log (user_id INTEGER, question TEXT, timestamp TEXT)")
conn.commit()

# ================== Допоміжні ==================

def get_user(uid):
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    return c.fetchone()

def add_user(uid, ref=None):
    if not get_user(uid):
        now = datetime.datetime.now() + datetime.timedelta(hours=1)
        c.execute("INSERT INTO users (id, usage, expires, referred_by) VALUES (?, ?, ?, ?)", (uid, 0, now.isoformat(), ref))
        if ref:
            c.execute("UPDATE users SET referrals = referrals + 1 WHERE id = ?", (ref,))
        conn.commit()

def log_usage(uid, text):
    now = datetime.datetime.now().isoformat()
    c.execute("INSERT INTO gpt_log VALUES (?, ?, ?)", (uid, text, now))
    c.execute("UPDATE users SET usage = usage + 1 WHERE id = ?", (uid,))
    conn.commit()

def can_use_gpt(uid):
    c.execute("SELECT usage FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    return row and row[0] < 5

def reset_usage():
    c.execute("UPDATE users SET usage = 0")
    conn.commit()

def get_top_users():
    c.execute("SELECT id, usage FROM users ORDER BY usage DESC LIMIT 5")
    return c.fetchall()

# ================== FSM ==================

class GPTState(StatesGroup):
    query = State()

class WeatherState(StatesGroup):
    city = State()

# ================== Кнопки ==================

def main_kb():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="GPT", callback_data="gpt"), InlineKeyboardButton(text="Погода", callback_data="weather")],
        [InlineKeyboardButton(text="Новини", callback_data="news"), InlineKeyboardButton(text="Ціни", callback_data="prices")],
        [InlineKeyboardButton(text="Графік BTC", callback_data="graph_BTCUSDT"), InlineKeyboardButton(text="Прогноз BTC", callback_data="predict_BTCUSDT")],
        [InlineKeyboardButton(text="Мої монети", callback_data="my_coins"), InlineKeyboardButton(text="Додати монету", callback_data="add_coin")],
        [InlineKeyboardButton(text="Оплата", callback_data="pay"), InlineKeyboardButton(text="Рефералка", callback_data="referral")],
    ])
    return kb

# ================== Callback ==================

@dp.callback_query(Text(startswith="gpt"))
async def handle_gpt(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    add_user(uid)
    if not can_use_gpt(uid):
        await callback.message.answer("Ви вичерпали 5 запитів GPT на сьогодні.")
        return
    await callback.message.answer("Напишіть запит до GPT:")
    await state.set_state(GPTState.query)
    await callback.answer()

@dp.message(GPTState.query)
async def gpt_query(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    if not get_user(uid):
        add_user(uid)
    if can_use_gpt(uid):
        await msg.answer("Обробляю GPT...")
        try:
            res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": msg.text}])
            text = res.choices[0].message.content
            log_usage(uid, msg.text)
            await msg.answer(text[:4000])
        except Exception as e:
            await msg.answer("Помилка GPT")
            logging.error(e)
    await state.clear()

@dp.callback_query(Text(startswith="weather"))
async def weather(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Напишіть назву міста")
    await state.set_state(WeatherState.city)
    await callback.answer()

@dp.message(WeatherState.city)
async def weather_msg(msg: types.Message, state: FSMContext):
    city = msg.text
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ua"
    r = requests.get(url).json()
    if r.get("cod") != 200:
        await msg.answer("Місто не знайдено")
        return
    w = r["weather"][0]["description"].capitalize()
    t = r["main"]["temp"]
    h = r["main"]["humidity"]
    await msg.answer(f"Погода в {city}:\n{w}\n🌡 Температура: {t}°C\n💧 Вологість: {h}%")
    await state.clear()

@dp.callback_query(Text(startswith="news"))
async def news(callback: types.CallbackQuery):
    async with httpx.AsyncClient() as cli:
        r = await cli.get("https://cryptopanic.com/api/developer/v2/posts/?auth_token=" + CRYPTOPANIC_API_KEY)
        posts = r.json().get("results", [])[:5]
        text = "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
        await callback.message.answer("📰 Останні новини:\n" + text)
    await callback.answer()

@dp.callback_query(Text(startswith="prices"))
async def prices(callback: types.CallbackQuery):
    r = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=[\"BTCUSDT\",\"ETHUSDT\"]")
    data = r.json()
    msg = "\n".join(f"{d['symbol']}: {d['price']}" for d in data)
    await callback.message.answer(msg)
    await callback.answer()

@dp.callback_query(Text(startswith="predict_"))
async def predict(callback: types.CallbackQuery):
    symbol = callback.data.split("_")[1]
    r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}").json()
    prompt = f"Прогноз по {symbol}:\nЦіна: {r['lastPrice']}, Зміна: {r['priceChangePercent']}%, Обʼєм: {r['volume']}"
    res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
    await callback.message.answer(res.choices[0].message.content[:4000])
    await callback.answer()

@dp.callback_query(Text(startswith="graph_"))
async def graph(callback: types.CallbackQuery):
    symbol = callback.data.split("_")[1]
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=24"
    r = requests.get(url).json()
    prices = [float(i[4]) for i in r]
    plt.figure(figsize=(8, 4))
    plt.plot(prices)
    plt.title(f"Графік {symbol}")
    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    await bot.send_photo(callback.from_user.id, photo=buf)
    await callback.answer()

@dp.callback_query(Text(startswith="pay"))
async def pay(callback: types.CallbackQuery):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Підписка на GPT"},
                "unit_amount": 300,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"https://t.me/{BOT_USERNAME}?start=success",
        cancel_url=f"https://t.me/{BOT_USERNAME}?start=cancel",
    )
    await callback.message.answer(f"Оплатіть за посиланням: {session.url}")
    await callback.answer()

@dp.callback_query(Text(startswith="referral"))
async def referral(callback: types.CallbackQuery):
    uid = callback.from_user.id
    await callback.message.answer(f"Ваше реферальне посилання:\nhttps://t.me/{BOT_USERNAME}?start={uid}")
    await callback.answer()

# ================== Автофункції ==================

async def auto_news():
    async with httpx.AsyncClient() as cli:
        r = await cli.get("https://cryptopanic.com/api/developer/v2/posts/?auth_token=" + CRYPTOPANIC_API_KEY)
        posts = r.json().get("results", [])[:3]
        text = "📰 Новини:\n" + "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
        await bot.send_message(CHANNEL_ID, text)

async def auto_predict():
    symbols = ["BTCUSDT", "ETHUSDT"]
    for symbol in symbols:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}").json()
        prompt = f"Прогноз по {symbol}:\nЦіна: {r['lastPrice']}, Зміна: {r['priceChangePercent']}%, Обʼєм: {r['volume']}"
        res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        await bot.send_message(CHANNEL_ID, res.choices[0].message.content[:4000])

# ================== Запуск ==================

def run():
    scheduler.add_job(auto_news, "interval", hours=1)
    scheduler.add_job(auto_predict, "interval", minutes=30)
    scheduler.add_job(reset_usage, "cron", hour=0)
    scheduler.start()
    asyncio.run(dp.start_polling(bot))

if __name__ == "__main__":
    threading.Thread(target=lambda: uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)).start()
    run()


