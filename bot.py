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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from config import (
    BOT_TOKEN, BOT_USERNAME, CRYPTO_PAY_TOKEN,
    CHANNEL_CHAT_ID, CHANNEL_LINK, TARIFFS,
    OWNER_ID, CRYPTOPANIC_API_KEY, OPENAI_API_KEY
)
from db import add_or_update_user, get_user_profile, get_all_users, remove_user

load_dotenv()
openai.api_key = OPENAI_API_KEY
logging.basicConfig(level=logging.INFO)

telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
fastapi_app = FastAPI()

# GPT usage DB
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
    },
    "commands_list": {
        "uk": "/start — стартове меню\n/myaccess — мій доступ\n/help — команди\n/admin — адмін-панель\n/ask — GPT\n/testask — тест для адміна\n/price — ціни\n/predict — прогноз по монеті\n/broadcast — розсилка (admin)",
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
    "gpt_limit": {"uk": "⚠️ Вичерпано 5 запитів на сьогодні.", "ru": "⚠️ Лимит 5 запросов исчерпан.", "en": "⚠️ You used 5 GPT requests today."}
}

user_lang = {}
def lang(uid): return user_lang.get(uid, "uk")
def tr(uid, key): return TEXT[key][lang(uid)]

# GPT usage check
def can_use_gpt(uid):
    today = datetime.date.today().isoformat()
    cursor.execute("SELECT COUNT(*) FROM gpt_usage WHERE user_id=? AND date=?", (uid, today))
    count = cursor.fetchone()[0]
    return count < 5

def log_gpt_usage(uid, prompt, tokens=0):
    today = datetime.date.today().isoformat()
    cursor.execute("INSERT INTO gpt_usage (user_id, date, prompt, tokens) VALUES (?, ?, ?, ?)", (uid, today, prompt, tokens))
    conn.commit()

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
    row = get_user_profile(uid)
    if row:
        days = (datetime.datetime.fromisoformat(row[1]) - datetime.datetime.now()).days
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
    msg = f"👥 Users: {len(users)}\n✅ Active: {active}\n❌ Inactive: {inactive}"
    await update.message.reply_text(msg)

async def ask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID and not get_user_profile(uid):
        return await update.message.reply_text(tr(uid, "no_access"))
    if not can_use_gpt(uid):
        return await update.message.reply_text(tr(uid, "gpt_limit"))
    q = " ".join(ctx.args)
    if not q:
        return await update.message.reply_text("🤖 Напиши запит після /ask")
    res = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": q}]
    )
    answer = res.choices[0].message.content
    log_gpt_usage(uid, q)
    await update.message.reply_text(answer[:4000])

async def testask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("⛔ Лише для адміна.")
    q = " ".join(ctx.args)
    res = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": q or "Hello!"}]
    )
    await update.message.reply_text(res.choices[0].message.content[:4000])

async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("⛔ Лише для адміна.")
    text = " ".join(ctx.args)
    users = get_all_users()
    count = 0
    for uid, _ in users:
        try:
            await telegram_app.bot.send_message(uid, text)
            count += 1
        except:
            pass
    await update.message.reply_text(f"✅ Надіслано {count} користувачам.")

async def price_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    r = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=[\"BTCUSDT\",\"ETHUSDT\"]")
    data = r.json()
    msg = "\n".join(f"{d['symbol']}: {d['price']}" for d in data)
    await update.message.reply_text(f"💱 Поточні ціни:\n{msg}")

async def predict_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID and not get_user_profile(uid):
        return await update.message.reply_text(tr(uid, "no_access"))
    if not ctx.args:
        return await update.message.reply_text(tr(uid, "predict_usage"))
    symbol = ctx.args[0].upper()
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}")
        d = r.json()
        prompt = f"Прогноз по {symbol}:\nЦіна: {d['lastPrice']}, Зміна: {d['priceChangePercent']}%, Обʼєм: {d['volume']}."
        res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        await update.message.reply_text(res.choices[0].message.content[:4000])
    except Exception as e:
        logging.error(e)
        await update.message.reply_text(tr(uid, "predict_error"))

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data
    if data.startswith("lang:"):
        code = data.split(":")[1]
        user_lang[uid] = code
        kb = [[InlineKeyboardButton(TEXT["buttons"][k][code], callback_data=k)]
              for k in ["access", "subscribe", "freetrial", "news", "commands"]]
        await q.edit_message_text(TEXT["main_menu"][code].format(name=q.from_user.first_name), reply_markup=InlineKeyboardMarkup(kb))
    elif data == "subscribe":
        code = lang(uid)
        kb = [[InlineKeyboardButton(TARIFFS[k]["labels"][code], callback_data=k)] for k in TARIFFS]
        await q.edit_message_text(TEXT["choose_tariff"][code], reply_markup=InlineKeyboardMarkup(kb))
    elif data in TARIFFS:
        t = TARIFFS[data]
        ctx.user_data["tdays"] = t["duration_days"]
        resp = requests.post("https://pay.crypt.bot/api/createInvoice", json={
            "asset": "USDT", "amount": t["amount"],
            "description": f"{t['duration_days']} days",
            "paid_btn_name": "openBot",
            "paid_btn_url": f"https://t.me/{BOT_USERNAME}",
            "payload": f"{uid}:{data}"
        }, headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN})
        rj = resp.json()
        if rj.get("ok"):
            url = rj["result"]["pay_url"]
            kb = [[InlineKeyboardButton("✅ Я оплатив", callback_data="check")]]
            await q.edit_message_text(f"💳 Оплатіть тут:\n{url}", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await q.edit_message_text("❌ Помилка створення рахунку.")
    elif data == "check":
        try:
            m = await ctx.bot.get_chat_member(CHANNEL_CHAT_ID, uid)
            if m.status in ["member", "administrator", "creator"]:
                add_or_update_user(uid, ctx.user_data.get("tdays", 30))
                await q.edit_message_text(tr(uid, "pay_success"))
            else:
                raise Exception()
        except:
            await q.edit_message_text(tr(uid, "not_subscribed") + CHANNEL_LINK)
    elif data == "freetrial":
        add_or_update_user(uid, 0.0417)
        await q.edit_message_text("✅ Безкоштовний доступ на 1 годину активовано!")
    elif data == "access":
        row = get_user_profile(uid)
        if row:
            days = (datetime.datetime.fromisoformat(row[1]) - datetime.datetime.now()).days
            await q.edit_message_text(tr(uid, "access_status").format(days=days))
        else:
            await q.edit_message_text(tr(uid, "no_access"))
    elif data == "news":
        await send_news(uid)
    elif data == "commands":
        await q.edit_message_text(TEXT["commands_list"][lang(uid)])

async def send_news(uid):
    async with httpx.AsyncClient() as cli:
        r = await cli.get("https://cryptopanic.com/api/developer/v2/posts/", params={"auth_token": CRYPTOPANIC_API_KEY, "public": "true"})
        posts = r.json().get("results", [])[:3]
    msg = "📰 Останні новини:\n" + "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
    await telegram_app.bot.send_message(uid, msg)

async def check_expiry(_):
    now = datetime.datetime.now()
    for uid, exp in get_all_users():
        dt = datetime.datetime.fromisoformat(exp)
        if (dt - now).days == 1:
            await telegram_app.bot.send_message(uid, "⚠️ Завтра завершується підписка.")
        if dt < now:
            remove_user(uid)

from uvicorn import Config, Server
async def main():
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_cmd))
    telegram_app.add_handler(CommandHandler("myaccess", myaccess_cmd))
    telegram_app.add_handler(CommandHandler("admin", admin_cmd))
    telegram_app.add_handler(CommandHandler("ask", ask_cmd))
    telegram_app.add_handler(CommandHandler("testask", testask_cmd))
    telegram_app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    telegram_app.add_handler(CommandHandler("price", price_cmd))
    telegram_app.add_handler(CommandHandler("predict", predict_cmd))
    telegram_app.add_handler(CallbackQueryHandler(handle_cb))
    telegram_app.job_queue.run_repeating(check_expiry, interval=3600)
    await telegram_app.initialize()
    config = Config(fastapi_app, host="0.0.0.0", port=8000)
    server = Server(config)
    await asyncio.gather(telegram_app.start(), server.serve())

if __name__ == "__main__":
    asyncio.run(main())
