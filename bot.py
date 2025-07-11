# ✅ Повний оновлений bot.py з /start, /help, /predict, GPT, Binance, FastAPI, безкоштовним доступом, адмін-панеллю
# ⚙️ Залежності: python-telegram-bot[fast], openai, python-dotenv, httpx, requests, apscheduler

import os
import asyncio
import datetime
import logging
import requests
import openai
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from config import (
    BOT_TOKEN, OWNER_ID, BOT_USERNAME,
    CRYPTOPANIC_API_KEY
)
from db import add_or_update_user, get_user_profile, get_all_users, remove_user

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

logging.basicConfig(level=logging.INFO)

telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
fastapi_app = FastAPI()

LANGUAGES = {"uk": "Українська", "ru": "Русский", "en": "English"}
user_lang = {}
def lang(uid): return user_lang.get(uid, "uk")

def tr(uid, key):
    return {
        "access_status": {"uk": "✅ Доступ активний, залишилось {days} днів", "ru": "✅ Доступ активен, осталось {days} дней", "en": "✅ Access active, {days} days left"},
        "no_access": {"uk": "❌ Немає активної підписки.", "ru": "❌ Нет подписки.", "en": "❌ No active subscription."},
    }[key][lang(uid)]

@fastapi_app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

# --- Нові функції /start і /help ---

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_lang.setdefault(uid, "uk")
    await update.message.reply_text(
        "Вітаю! Це стартове меню.\nВикористовуйте /help для списку команд."
    )
    logging.info(f"/start від користувача {uid}")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (
        "/start — стартове меню\n"
        "/myaccess — мій доступ\n"
        "/help — команди\n"
        "/admin — адмін-панель\n"
        "/ask — GPT\n"
        "/testask — тестова команда (адмін)\n"
        "/price — ціни\n"
        "/predict — прогноз крипти"
    )
    await update.message.reply_text(text)
    logging.info(f"/help від користувача {uid}")

# --- Існуючі команди ---

async def ask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID and not get_user_profile(uid):
        await update.message.reply_text(tr(uid, "no_access"))
        return
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("🤖 Напиши запит після /ask")
        return
    logging.info(f"/ask від {uid}: {q}")
    res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": q}])
    await update.message.reply_text(res.choices[0].message.content[:4000])

async def testask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Лише для адміністратора.")
        return
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("🤖 Напиши тест-запит після /testask")
        return
    res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": q}])
    await update.message.reply_text("🧪 Test Answer:\n" + res.choices[0].message.content[:4000])

async def predict_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID and not get_user_profile(uid):
        await update.message.reply_text("⛔ У вас немає доступу до цієї функції.")
        return
    if not ctx.args:
        await update.message.reply_text("📊 Напишіть команду у форматі: /predict BTCUSDT")
        return
    symbol = ctx.args[0].upper()
    try:
        data = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}").json()
        prompt = (
            f"Монета: {symbol}\n"
            f"Поточна ціна: {data['lastPrice']}\n"
            f"Зміна за 24h: {data['priceChangePercent']}%\n"
            f"Обʼєм: {data['volume']}\n"
            f"На основі цих даних спрогнозуй, чи варто купувати або продавати."
        )
        res = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        await update.message.reply_text(f"📈 Прогноз для {symbol}:\n{res.choices[0].message.content[:4000]}")
    except Exception as e:
        logging.error(f"Error in /predict: {e}")
        await update.message.reply_text("❌ Помилка отримання даних або прогнозу.")

async def price_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=[\"BTCUSDT\",\"ETHUSDT\"]").json()
    await update.message.reply_text("💱 Поточні ціни:\n" + "\n".join(f"{d['symbol']}: {d['price']}" for d in data))

async def myaccess_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == OWNER_ID:
        add_or_update_user(uid, 3650)  # 10 років
    row = get_user_profile(uid)
    if row:
        days = (datetime.datetime.fromisoformat(row[1]) - datetime.datetime.now()).days
        await update.message.reply_text(tr(uid, "access_status").format(days=days))
    else:
        await update.message.reply_text(tr(uid, "no_access"))

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Access denied.")
        return
    users = get_all_users()
    active = sum(datetime.datetime.fromisoformat(exp) > datetime.datetime.now() for _, exp in users)
    inactive = len(users) - active
    await update.message.reply_text(f"👥 Users: {len(users)}\n✅ Active: {active}\n❌ Inactive: {inactive}")

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
    telegram_app.add_handler(CommandHandler("start", start_cmd))
    telegram_app.add_handler(CommandHandler("help", help_cmd))
    telegram_app.add_handler(CommandHandler("ask", ask_cmd))
    telegram_app.add_handler(CommandHandler("testask", testask_cmd))
    telegram_app.add_handler(CommandHandler("predict", predict_cmd))
    telegram_app.add_handler(CommandHandler("price", price_cmd))
    telegram_app.add_handler(CommandHandler("myaccess", myaccess_cmd))
    telegram_app.add_handler(CommandHandler("admin", admin_cmd))
    telegram_app.job_queue.run_repeating(check_expiry, interval=3600)
    await telegram_app.initialize()

    config = Config(fastapi_app, host="0.0.0.0", port=8000)
    server = Server(config)

    await asyncio.gather(
        telegram_app.start(),
        server.serve()
    )

if __name__ == "__main__":
    asyncio.run(main())
