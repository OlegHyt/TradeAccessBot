import os
import asyncio
import datetime
import logging
import sqlite3
import requests
import httpx
import io
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Update
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from openai import OpenAI
import stripe

import uvicorn
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
OWNER_ID = int(os.getenv("OWNER_ID"))
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")
CHANNEL_CHAT_ID = int(os.getenv("CHANNEL_CHAT_ID"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK")
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

# ================= DB =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    usage INTEGER DEFAULT 0,
    expires TEXT
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
        "INSERT OR REPLACE INTO users (id, usage, expires) VALUES (?, COALESCE((SELECT usage FROM users WHERE id=?), 0), ?)",
        (uid, uid, new_expiry.isoformat())
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
    usage, expires = row
    if expires:
        expiry_date = datetime.datetime.fromisoformat(expires)
        if expiry_date < datetime.datetime.now():
            return False
    return usage < 5

def reset_usage():
    c.execute("UPDATE users SET usage = 0")
    conn.commit()

# ================= FSM =================
class GPTState(StatesGroup):
    waiting = State()

class WeatherState(StatesGroup):
    waiting = State()

# ================= KEYBOARDS =================
def main_kb():
    kb = [
        [InlineKeyboardButton("📊 Доступ", callback_data="access"),
         InlineKeyboardButton("💳 Оплата", callback_data="pay")],
        [InlineKeyboardButton("🧠 GPT", callback_data="gpt"),
         InlineKeyboardButton("☀️ Погода", callback_data="weather")],
        [InlineKeyboardButton("📰 Новини", callback_data="news"),
         InlineKeyboardButton("💱 Ціни", callback_data="prices")]
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

# ================= COMMANDS =================
@dp.message(Command("start"))
async def start(msg: types.Message):
    uid = msg.from_user.id
    args = msg.get_args() if hasattr(msg, "get_args") else ""
    if not get_user(uid):
        add_or_update_user(uid, 1)
    await msg.answer(f"Вітаю, {msg.from_user.first_name}!", reply_markup=main_kb())
    # Якщо прийшов параметр start=success чи cancel, можна додати логіку

@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    await msg.answer("/start — почати\n/help — допомога\n")

# ================= CALLBACKS =================
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
                "unit_amount": 599,  # 5.99 USD у центах
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
                "unit_amount": 3999,  # 39.99 USD у центах
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"https://t.me/{BOT_USERNAME}?start=success",
        cancel_url=f"https://t.me/{BOT_USERNAME}?start=cancel",
    )
    await cb.message.answer(f"Оплатіть тут: {session.url}")
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
    async with httpx.AsyncClient() as cli:
        r = await cli.get(f"https://cryptopanic.com/api/developer/v2/posts/?auth_token={CRYPTOPANIC_API_KEY}")
        posts = r.json().get("results", [])[:5]
        # Для прикладу виведемо на трьох мовах — тут просто дублюємо текст:
        text_ua = "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
        text_ru = "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))  # Можна перекладати або інші API
        text_en = "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
        await cb.message.answer("📰 Останні новини (UA):\n" + text_ua)
        await cb.message.answer("📰 Последние новости (RU):\n" + text_ru)
        await cb.message.answer("📰 Latest news (EN):\n" + text_en)
    await cb.answer()

@dp.callback_query(lambda c: c.data == "prices")
async def cb_prices(cb: types.CallbackQuery):
    r = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=[\"BTCUSDT\",\"ETHUSDT\"]")
    prices = r.json()
    msg = "\n".join(f"{d['symbol']}: {d['price']}" for d in prices)
    await cb.message.answer("💱 Поточні курси:\n" + msg)
    await cb.answer()

# ================= НОВЕ АВТОЗАВДАННЯ =================
async def send_candlestick_and_forecast():
    symbols = ["BTCUSDT", "ETHUSDT"]
    interval = "1d"  # добовий інтервал

    async with httpx.AsyncClient() as client:
        for symbol in symbols:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=30"
            resp = await client.get(url)
            data = resp.json()

            # Формуємо DataFrame
            df = pd.DataFrame(data, columns=[
                "Open time", "Open", "High", "Low", "Close", "Volume",
                "Close time", "Quote asset volume", "Number of trades",
                "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"
            ])
            df["Open time"] = pd.to_datetime(df["Open time"], unit='ms')
            df.set_index("Open time", inplace=True)
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                df[col] = df[col].astype(float)

            # Малюємо свічковий графік
            fig, axlist = mpf.plot(df.iloc[-30:], type='candle', style='charles',
                                   title=f"{symbol} - 30d Candlestick", returnfig=True)

            # Прогноз на основі простих ковзних середніх
            sma_short = df["Close"].rolling(window=5).mean().iloc[-1]
            sma_long = df["Close"].rolling(window=20).mean().iloc[-1]
            last_close = df["Close"].iloc[-1]

            if sma_short > sma_long and last_close > sma_short:
                forecast = "📈 Тренд зростає — потенційний сигнал купівлі."
            elif sma_short < sma_long and last_close < sma_short:
                forecast = "📉 Тренд падає — потенційний сигнал продажу."
            else:
                forecast = "⚖️ Тренд нейтральний — варто утриматись."

            # Зберігаємо графік в буфер
            buf = io.BytesIO()
            fig.savefig(buf, format='png')
            buf.seek(0)
            plt.close(fig)

            # Відправляємо у канал
            await bot.send_photo(CHANNEL_CHAT_ID, photo=buf, caption=forecast)

# ================= FASTAPI WEBHOOK =================
@fastapi_app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    if "payload" in body:
        uid, days = body["payload"].split(":")
        add_or_update_user(int(uid), int(days))
        return {"ok": True}

    update = Update(**body)
    await dp.feed_update(bot, update)
    return {"ok": True}

# ================= AUTOTASK =================
async def auto_news():
    async with httpx.AsyncClient() as cli:
        r = await cli.get(f"https://cryptopanic.com/api/developer/v2/posts/?auth_token={CRYPTOPANIC_API_KEY}")
        posts = r.json().get("results", [])[:3]
        text = "📰 Новини:\n" + "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
        await bot.send_message(CHANNEL_CHAT_ID, text)

# ================= RUN =================
def run():
    scheduler.add_job(auto_news, "interval", hours=1)
    scheduler.add_job(reset_usage, "cron", hour=0)
    scheduler.add_job(send_candlestick_and_forecast, "cron", hour=9)  # щоденно о 9 ранку
    scheduler.start()
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
