# ✅ Повний робочий bot.py (версія з GPT-4o, Binance, /ask, /price, FastAPI, локалізацією, оплатою, webhook)
# ⚙️ Залежності: python-telegram-bot[fast], openai, python-dotenv, httpx, requests, apscheduler

import os
import asyncio
import datetime
import logging
import requests
import httpx
import openai
import uvicorn
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

LANGUAGES = {"uk": "Українська", "ru": "Русский", "en": "English"}

TEXT = {
    "choose_lang": {"uk": "Оберіть мову:", "ru": "Выберите язык:", "en": "Choose your language:"},
    "main_menu": {"uk": "Вітаю, {name}!
Оберіть:", "ru": "Привет, {name}!
Выберите:", "en": "Welcome, {name}!
Choose:"},
    "buttons": {
        "access": {"uk": "📊 Мій доступ", "ru": "📊 Мой доступ", "en": "📊 My Access"},
        "subscribe": {"uk": "🔁 Продовжити підписку", "ru": "🔁 Продлить подписку", "en": "🔁 Renew Subscription"},
        "news": {"uk": "📰 Новини", "ru": "📰 Новости", "en": "📰 News"},
        "commands": {"uk": "📌 Команди", "ru": "📌 Команды", "en": "📌 Commands"},
    },
    "commands_list": {
        "uk": "/start — стартове меню
/myaccess — мій доступ
/help — команди
/admin — адмін-панель
/ask — GPT
/price — ціни",
        "ru": "/start — главное меню
/myaccess — мой доступ
/help — команды
/admin — админ-панель
/ask — GPT
/price — цены",
        "en": "/start — main menu
/myaccess — my access
/help — commands
/admin — admin panel
/ask — GPT
/price — prices"
    },
    "choose_tariff": {"uk": "Оберіть тариф:", "ru": "Выберите тариф:", "en": "Choose tariff:"},
    "pay_success": {"uk": "✅ Доступ активовано!", "ru": "✅ Доступ активирован!", "en": "✅ Access activated!"},
    "not_subscribed": {"uk": "❌ Не підписані. Підпишіться: ", "ru": "❌ Не подписаны. Подпишитесь: ", "en": "❌ Not subscribed. Subscribe: "},
    "access_status": {"uk": "✅ Доступ активний, залишилось {days} днів", "ru": "✅ Доступ активен, осталось {days} дней", "en": "✅ Access active, {days} days left"},
    "no_access": {"uk": "❌ Немає активної підписки.", "ru": "❌ Нет подписки.", "en": "❌ No active subscription."},
}

user_lang = {}
def lang(uid): return user_lang.get(uid, "uk")
def tr(uid, key): return TEXT[key][lang(uid)]

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
        await update.message.reply_text("⛔ Access denied.")
        return
    text = update.message.text
    users = get_all_users()
    active, inactive = 0, 0
    now = datetime.datetime.now()

    for _, exp in users:
        if datetime.datetime.fromisoformat(exp) > now:
            active += 1
        else:
            inactive += 1

    msg = f"👥 Users: {len(users)}
✅ Active: {active}
❌ Inactive: {inactive}"

    if " " in text:
        q = text.split(" ", 1)[1].strip()
        for u, exp in users:
            try:
                chat = await ctx.bot.get_chat(u)
                name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
                if q.lower() in name.lower() or q == str(u):
                    left = (datetime.datetime.fromisoformat(exp) - now).days
                    msg += f"

🔍 Found: {name}
ID: {u}
⏳ Days left: {max(0, left)}"
                    break
            except: pass
        else:
            msg += "

🚫 Not found."

    await update.message.reply_text(msg)

async def ask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID and not get_user_profile(uid):
        await update.message.reply_text(tr(uid, "no_access"))
        return
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("🤖 Напиши запит після /ask")
        return
    res = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": q}]
    )
    answer = res.choices[0].message.content
    await update.message.reply_text(answer[:4000])

async def price_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    r = requests.get("https://api.binance.com/api/v3/ticker/price?symbols=["BTCUSDT","ETHUSDT"]")
    data = r.json()
    msg = "
".join(f"{d['symbol']}: {d['price']}" for d in data)
    await update.message.reply_text(f"💱 Поточні ціни:
{msg}")

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data.startswith("lang:"):
        code = data.split(":")[1]
        user_lang[uid] = code
        name = q.from_user.first_name
        kb = [[InlineKeyboardButton(TEXT["buttons"][k][code], callback_data=k)] for k in ["access", "subscribe", "news", "commands"]]
        await q.edit_message_text(TEXT["main_menu"][code].format(name=name), reply_markup=InlineKeyboardMarkup(kb))

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
            await q.edit_message_text(f"💳 Оплатіть тут:
{url}", reply_markup=InlineKeyboardMarkup(kb))
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
        r = await cli.get("https://cryptopanic.com/api/developer/v2/posts/",
                          params={"auth_token": CRYPTOPANIC_API_KEY, "public": "true", "kind": "news"})
        posts = r.json().get("results", [])[:3]
    msg = "📰 Останні новини:
" + "
".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
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
    telegram_app.add_handler(CommandHandler("price", price_cmd))
    telegram_app.add_handler(CallbackQueryHandler(handle_cb))
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