import os
import asyncio
import datetime
import logging
import sqlite3
import requests
import httpx
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Update
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import stripe
import uvicorn
from openai import OpenAI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === LOAD ENV ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
OWNER_ID = int(os.getenv("OWNER_ID"))
CHANNEL_CHAT_ID = int(os.getenv("CHANNEL_CHAT_ID"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")

stripe.api_key = STRIPE_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
fastapi_app = FastAPI()
scheduler = AsyncIOScheduler()

# === DB ===
conn = sqlite3.connect("bot.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    usage INTEGER DEFAULT 0,
    expires TEXT,
    lang TEXT DEFAULT 'ua'
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS gpt_log (
    user_id INTEGER,
    question TEXT,
    timestamp TEXT
)
""")
conn.commit()

def add_or_update_user(uid, days=30):
    now = datetime.datetime.now()
    new_expiry = now + datetime.timedelta(days=days)
    c.execute(
        "INSERT OR REPLACE INTO users (id, usage, expires, lang) VALUES (?, COALESCE((SELECT usage FROM users WHERE id=?), 0), ?, COALESCE((SELECT lang FROM users WHERE id=?), 'ua'))",
        (uid, uid, new_expiry.isoformat(), uid)
    )
    conn.commit()

def get_user(uid):
    c.execute("SELECT * FROM users WHERE id=?", (uid,))
    return c.fetchone()

def log_gpt(uid, prompt):
    now = datetime.datetime.now().isoformat()
    c.execute("INSERT INTO gpt_log VALUES (?, ?, ?)", (uid, prompt, now))
    c.execute("UPDATE users SET usage = usage + 1 WHERE id = ?", (uid,))
    conn.commit()

def can_use_gpt(uid):
    c.execute("SELECT usage, expires FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    if not row:
        return False
    usage, expires = row[1], row[2]
    if expires:
        expiry_date = datetime.datetime.fromisoformat(expires)
        if expiry_date < datetime.datetime.now():
            return False
    return usage < 5

def reset_usage():
    c.execute("UPDATE users SET usage = 0")
    conn.commit()

def update_user_lang(uid, lang):
    c.execute("UPDATE users SET lang=? WHERE id=?", (lang, uid))
    conn.commit()

# === FSM ===
class GPTState(StatesGroup):
    waiting = State()

class WeatherState(StatesGroup):
    waiting = State()

# === KEYBOARDS ===
def main_kb():
    kb = [
        [InlineKeyboardButton(text="📊 Доступ", callback_data="access"),
         InlineKeyboardButton(text="💳 Оплата", callback_data="pay")],
        [InlineKeyboardButton(text="🧠 GPT", callback_data="gpt"),
         InlineKeyboardButton(text="☀️ Погода", callback_data="weather")],
        [InlineKeyboardButton(text="📰 Новини", callback_data="news"),
         InlineKeyboardButton(text="💱 Ціни", callback_data="prices")],
        [InlineKeyboardButton(text="🌐 Мова", callback_data="lang")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def payment_kb():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 5.99 USDT / 30 днів", callback_data="pay_30d"),
            InlineKeyboardButton(text="💎 39.99 USDT / 365 днів", callback_data="pay_365d"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
        ]
    ])
    return kb

def lang_kb():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang_ua"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
        ]
    ])
    return kb

# === COMMANDS ===
@dp.message(Command("start"))
async def start(msg: types.Message):
    uid = msg.from_user.id
    if not get_user(uid):
        add_or_update_user(uid, 1)
    await msg.answer(f"Вітаю, {msg.from_user.first_name}!", reply_markup=main_kb())

@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    await msg.answer("/start — почати\n/help — допомога\n")

# === CALLBACKS ===
@dp.callback_query(lambda c: c.data == "access")
async def cb_access(cb: types.CallbackQuery):
    uid = cb.from_user.id
    row = get_user(uid)
    if uid == OWNER_ID:
        await cb.message.answer("👑 Безліміт (адмін).")
    elif row:
        left = (datetime.datetime.fromisoformat(row[2]) - datetime.datetime.now()).days
        if left >= 0:
            await cb.message.answer(f"✅ Доступ активний: {left} днів")
        else:
            await cb.message.answer("❌ Підписка неактивна.")
    else:
        await cb.message.answer("❌ Підписка неактивна.")
    await cb.answer()

@dp.callback_query(lambda c: c.data == "pay")
async def cb_pay_menu(cb: types.CallbackQuery):
    await cb.message.answer("Оберіть тариф для оплати:", reply_markup=payment_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "pay_30d")
async def cb_pay_30d(cb: types.CallbackQuery):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Підписка 30 днів"},
                "unit_amount": 599,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"https://t.me/{BOT_USERNAME}?start=success",
        cancel_url=f"https://t.me/{BOT_USERNAME}?start=cancel",
    )
    await cb.message.answer(f"Оплатіть тут: {session.url}")
    await cb.answer()

@dp.callback_query(lambda c: c.data == "pay_365d")
async def cb_pay_365d(cb: types.CallbackQuery):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Підписка 365 днів"},
                "unit_amount": 3999,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"https://t.me/{BOT_USERNAME}?start=success",
        cancel_url=f"https://t.me/{BOT_USERNAME}?start=cancel",
    )
    await cb.message.answer(f"Оплатіть тут: {session.url}")
    await cb.answer()

@dp.callback_query(lambda c: c.data == "lang")
async def cb_lang(cb: types.CallbackQuery):
    await cb.message.answer("Оберіть мову:", reply_markup=lang_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("lang_"))
async def cb_set_lang(cb: types.CallbackQuery):
    uid = cb.from_user.id
    lang = cb.data.split("_")[1]
    update_user_lang(uid, lang)
    await cb.message.answer(f"✅ Мову встановлено: {lang.upper()}", reply_markup=main_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def cb_back(cb: types.CallbackQuery):
    await cb.message.answer("Головне меню:", reply_markup=main_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "gpt")
async def cb_gpt(cb: types.CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    if not can_use_gpt(uid):
        await cb.message.answer("⚠️ Вичерпано 5 запитів сьогодні.")
        await cb.answer()
        return
    await cb.message.answer("Введіть запит для GPT:")
    await state.set_state(GPTState.waiting)
    await cb.answer()

@dp.message(GPTState.waiting)
async def gpt_reply(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    if can_use_gpt(uid):
        await msg.answer("Обробляю...")
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": msg.text}]
            )
            answer = resp.choices[0].message.content
            log_gpt(uid, msg.text)
            await msg.answer(answer[:4000])
        except Exception as e:
            await msg.answer("❌ Помилка GPT.")
            logging.error(e)
    await state.clear()

@dp.callback_query(lambda c: c.data == "weather")
async def cb_weather(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Введіть місто:")
    await state.set_state(WeatherState.waiting)
    await cb.answer()

@dp.message(WeatherState.waiting)
async def weather_reply(msg: types.Message, state: FSMContext):
    city = msg.text
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ua"
    r = requests.get(url).json()
    if r.get("cod") != 200:
        await msg.answer("Місто не знайдено.")
    else:
        w = r["weather"][0]["description"].capitalize()
        t = r["main"]["temp"]
        await msg.answer(f"Погода: {w}\n🌡 Температура: {t}°C")
    await state.clear()

@dp.callback_query(lambda c: c.data == "news")
async def cb_news(cb: types.CallbackQuery):
    uid = cb.from_user.id
    user = get_user(uid)
    lang = user[3] if user else "ua"

    async with httpx.AsyncClient() as cli:
        r = await cli.get(f"https://cryptopanic.com/api/developer/v2/posts/?auth_token={CRYPTOPANIC_API_KEY}")
        posts = r.json().get("results", [])[:5]

        text = "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))

        if lang == "ua":
            prefix = "📰 Останні новини (UA):"
        elif lang == "ru":
            prefix = "📰 Последние новости (RU):"
        else:
            prefix = "📰 Latest news (EN):"

        await cb.message.answer(f"{prefix}\n{text}")

    await cb.answer()

@dp.callback_query(lambda c: c.data == "prices")
async def cb_prices(cb: types.CallbackQuery):
    async with httpx.AsyncClient() as cli:
        btc_r = await cli.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
        eth_r = await cli.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT")
        btc = btc_r.json().get("price")
        eth = eth_r.json().get("price")
        await cb.message.answer(f"💱 BTC/USDT: {btc}\n💱 ETH/USDT: {eth}")
    await cb.answer()

# === WEBHOOK FOR TELEGRAM AND CRYPTO PAY ===
@fastapi_app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()

    # Якщо це повідомлення від Crypto Pay (платіж)
    if "payload" in data:
        try:
            uid_str, days_str = data["payload"].split(":")
            uid, days = int(uid_str), int(days_str)
            add_or_update_user(uid, days)
            return JSONResponse(content={"ok": True})
        except Exception as e:
            logging.error(f"Crypto Pay webhook error: {e}")
            return JSONResponse(content={"ok": False}, status_code=400)

    # Інакше це оновлення від Telegram
    update = Update(**data)
    await dp.feed_update(bot, update)
    return JSONResponse(content={"ok": True})

# === RUN ===
def run():
    scheduler.add_job(reset_usage, "cron", hour=0)
    scheduler.start()
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
