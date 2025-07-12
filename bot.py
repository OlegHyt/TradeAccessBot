import os
# 🔧 Test change
import asyncio
import datetime
from io import BytesIO

import httpx
import matplotlib.pyplot as plt
import stripe
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from openai import OpenAI

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from db import init_db, get_conn

# Завантажуємо .env
load_dotenv()
stripe.api_key = config.STRIPE_API_KEY
openai = OpenAI(api_key=config.OPENAI_API_KEY)

# Ініціалізуємо БД
init_db()
conn = get_conn()
c = conn.cursor()

# Ініціалізація бота, диспетчера, FastAPI, планувальника
bot = Bot(token=config.BOT_TOKEN, default=types.DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(bot=bot, storage=MemoryStorage())
app = FastAPI()
scheduler = AsyncIOScheduler()

# Допоміжні функції для роботи з БД
def get_user(uid):
    c.execute("SELECT * FROM users WHERE id=?", (uid,))
    return c.fetchone()

def add_or_update_user(uid, days=30, ref=None):
    now = datetime.datetime.now()
    exp = (now + datetime.timedelta(days=days)).isoformat()
    if get_user(uid):
        c.execute("UPDATE users SET expires=?, usage=0 WHERE id=?", (exp, uid))
    else:
        c.execute("INSERT INTO users (id, expires, referrals) VALUES (?, ?, 0)", (uid, exp))
        if ref:
            c.execute("UPDATE users SET referrals = referrals + 1 WHERE id=?", (ref,))
    conn.commit()

def can_use_gpt(uid):
    row = get_user(uid)
    if not row: return False
    usage, expires = row[1], row[2]
    if expires and datetime.datetime.fromisoformat(expires) < datetime.datetime.now():
        return False
    return usage < 5 or uid == config.OWNER_ID

def log_gpt(uid, question):
    ts = datetime.datetime.now().isoformat()
    c.execute("INSERT INTO gpt_log VALUES (?, ?, ?)", (uid, question, ts))
    if uid != config.OWNER_ID:
        c.execute("UPDATE users SET usage = usage + 1 WHERE id=?", (uid,))
    conn.commit()

def reset_daily_usage():
    c.execute("UPDATE users SET usage = 0")
    conn.commit()

# FSM стани
class GPTState(StatesGroup):
    waiting = State()

class WeatherState(StatesGroup):
    waiting = State()

# Клавіатури
def main_kb():
    kb = [
        [InlineKeyboardButton("📊 Доступ", callback_data="access"),
         InlineKeyboardButton("💳 Оплата", callback_data="pay")],
        [InlineKeyboardButton("🧠 GPT", callback_data="gpt"),
         InlineKeyboardButton("☀️ Погода", callback_data="weather")],
        [InlineKeyboardButton("📰 Новини", callback_data="news"),
         InlineKeyboardButton("💱 Ціни", callback_data="prices")],
        [InlineKeyboardButton("📈 Графік", callback_data="graph"),
         InlineKeyboardButton("🔧 Адмін", callback_data="admin") if config.OWNER_ID else None]
    ]
    return InlineKeyboardMarkup([[b for b in row if b] for row in kb])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back")]])

def pay_kb():
    buttons = []
    for key, t in config.TARIFFS.items():
        buttons.append(InlineKeyboardButton(f"{t['amount_cents']/100:.2f} USDT / {t['days']}d", callback_data=f"pay_{key}"))
    return InlineKeyboardMarkup([buttons, [InlineKeyboardButton("⬅️ Назад", callback_data="back")]])

# /start
@dp.message(Command("start"))
async def on_start(msg: types.Message):
    uid = msg.from_user.id
    parts = msg.text.split()
    ref = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    add_or_update_user(uid, days=1, ref=ref)
    await msg.answer(f"👋 Привіт, {msg.from_user.first_name}!", reply_markup=main_kb())

# Доступ
@dp.callback_query(lambda c: c.data == "access")
async def cb_access(cb: types.CallbackQuery):
    uid = cb.from_user.id
    if uid == config.OWNER_ID:
        txt = "👑 Адмін: безліміт"
    else:
        row = get_user(uid)
        txt = (f"✅ Доступ активний, днів лишилось: "
               f"{max((datetime.datetime.fromisoformat(row[2]) - datetime.datetime.now()).days, 0)}") if row else "❌ Підписка неактивна"
    await cb.message.answer(txt, reply_markup=back_kb())
    await cb.answer()

# Оплата
@dp.callback_query(lambda c: c.data == "pay")
async def cb_pay(cb: types.CallbackQuery):
    await cb.message.answer("🛒 Обери тариф:", reply_markup=pay_kb())
    await cb.answer()

def create_stripe_link(days: int, user_id: int):
    sess = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Підписка {days} днів"},
                "unit_amount": config.TARIFFS[str(days)]["amount_cents"]
            },
            "quantity": 1
        }],
        mode="payment",
        success_url=f"https://t.me/{config.BOT_USERNAME}?start=success",
        cancel_url=f"https://t.me/{config.BOT_USERNAME}?start=cancel",
        metadata={"user_id": user_id}
    )
    return sess.url

@dp.callback_query(lambda c: c.data.startswith("pay_"))
async def cb_pay_option(cb: types.CallbackQuery):
    uid = cb.from_user.id
    days = int(cb.data.split("_")[1])
    url = create_stripe_link(days, uid)
    await cb.message.answer(f"Оплатіть тут: {url}")
    await cb.answer()

# Stripe webhook
@app.post("/stripe_webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, config.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = int(session['metadata'].get('user_id', 0))
        days = 30 if "30" in session['display_items'][0]['custom']['name'] else 365
        add_or_update_user(user_id, days=days)
    return JSONResponse(status_code=200, content={"success": True})

# GPT
async def ask_gpt(q: str) -> str:
    try:
        resp = await openai.chat.completions.acreate(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":q}],
            max_tokens=300, temperature=0.6
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"GPT error: {e}"

@dp.callback_query(lambda c: c.data == "gpt")
async def cb_gpt(cb: types.CallbackQuery):
    uid = cb.from_user.id
    if not can_use_gpt(uid):
        await cb.message.answer("❌ Ліміт або підписка неактивна.")
    else:
        await cb.message.answer("🧠 Напиши своє запитання:")
        await GPTState.waiting.set()

@dp.message(GPTState.waiting)
async def on_gpt(msg: types.Message, state: FSMContext):
    uid, q = msg.from_user.id, msg.text
    await msg.answer("⌛ Пишу відповідь...")
    ans = await ask_gpt(q)
    log_gpt(uid, q)
    await msg.answer(ans, reply_markup=main_kb())
    await state.clear()

# Погода
async def get_weather(city: str) -> str:
    url = (f"http://api.openweathermap.org/data/2.5/weather"
           f"?q={city}&appid={config.OPENWEATHER_API_KEY}"
           f"&units=metric&lang=ua")
    async with httpx.AsyncClient() as cli:
        r = await cli.get(url)
    if r.status_code != 200: return "Не вдалося отримати погоду."
    d = r.json()
    return (f"Погода в {city}:\n"
            f"{d['weather'][0]['description'].capitalize()}\n"
            f"Темп: {d['main']['temp']}°C, Вологість: {d['main']['humidity']}%, "
            f"Вітер: {d['wind']['speed']} м/с")

@dp.callback_query(lambda c: c.data == "weather")
async def cb_weather(cb: types.CallbackQuery):
    await cb.message.answer("Введи місто для погоди:")
    await WeatherState.waiting.set()

@dp.message(WeatherState.waiting)
async def on_weather(msg: types.Message, state: FSMContext):
    w = await get_weather(msg.text.strip())
    await msg.answer(w, reply_markup=main_kb())
    await state.clear()

# Новини
async def get_news():
    url = (f"https://cryptopanic.com/api/v1/posts/"
           f"?auth_token={config.CRYPTOPANIC_API_KEY}&public=true&kind=news")
    async with httpx.AsyncClient() as cli:
        r = await cli.get(url)
    return r.json().get("results", []) if r.status_code == 200 else []

@dp.callback_query(lambda c: c.data == "news")
async def cb_news(cb: types.CallbackQuery):
    news = await get_news()
    if not news:
        await cb.message.answer("Не вдалося завантажити новини.")
    else:
        msgs = [f"• <a href='{i['url']}'>{i['title']}</a>" for i in news[:5]]
        await cb.message.answer(
            "\n".join(msgs),
            disable_web_page_preview=True,
            reply_markup=main_kb()
        )

# Графік BTC
async def fetch_price(sym: str):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
    async with httpx.AsyncClient() as cli:
        r = await cli.get(url)
    return float(r.json().get("price", 0))

async def draw_chart():
    now = datetime.datetime.now()
    times, vals = [], []
    for i in range(10):
        t = now - datetime.timedelta(minutes=10 * i)
        times.append(t.strftime("%H:%M"))
        vals.append(await fetch_price("BTCUSDT"))
        await asyncio.sleep(0.1)
    times.reverse(); vals.reverse()
    plt.figure(figsize=(8, 4))
    plt.plot(times, vals, label="BTCUSDT")
    plt.xticks(rotation=45); plt.title("Графік BTC"); plt.grid(); plt.legend()
    buf = BytesIO(); plt.tight_layout(); plt.savefig(buf, format="png"); buf.seek(0); plt.close()
    return buf

@dp.callback_query(lambda c: c.data == "graph")
async def cb_graph(cb: types.CallbackQuery):
    await cb.message.answer("Побудова графіку...")
    img = await draw_chart()
    await cb.message.answer_photo(img, reply_markup=main_kb())

# Планувальник
async def daily_reset(): reset_daily_usage()
async def scheduled_news():
    news = await get_news()
    if news:
        msgs = [f"• {i['title']}" for i in news[:3]]
        await bot.send_message(config.CHANNEL_CHAT_ID, "📰 Останні новини:\n" + "\n".join(msgs))

scheduler.add_job(daily_reset, 'cron', hour=0, minute=0)
scheduler.add_job(scheduled_news, 'interval', minutes=60)

# Telegram webhook endpoint
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = types.Update(**data)
    await dp.process_update(update)
    return JSONResponse({"ok": True})

# Запуск при стартапі/шутдауні
@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(config.WEBHOOK_URL, drop_pending_updates=True)
    scheduler.start()

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()

# Головний запуск
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
