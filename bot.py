import asyncio
import datetime
import logging
import requests
import httpx
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
)
from config import (
    BOT_TOKEN, BOT_USERNAME, TARIFFS,
    CRYPTO_PAY_TOKEN, CHANNEL_CHAT_ID, CHANNEL_LINK,
    CRYPTOPANIC_API_KEY
)
from db import add_or_update_user, get_user_profile, get_all_users, remove_user

# 🔐 Власник бота
OWNER_ID = 6800873578

logging.basicConfig(level=logging.INFO)

fastapi_app = FastAPI()
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

# 🌐 Локалізація
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
        "news": {"uk": "📰 Новини", "ru": "📰 Новости", "en": "📰 News"},
        "commands": {"uk": "📌 Команди", "ru": "📌 Команды", "en": "📌 Commands"},
    },
    "commands_list": {
        "uk": "/start — стартове меню\n/myaccess — мій доступ\n/help — команди\n/admin — адмін-панель",
        "ru": "/start — главное меню\n/myaccess — мой доступ\n/help — команды\n/admin — админ-панель",
        "en": "/start — main menu\n/myaccess — my access\n/help — commands\n/admin — admin panel"
    },
    "choose_tariff": {
        "uk": "Оберіть тариф:", "ru": "Выберите тариф:", "en": "Choose tariff:"
    },
    "pay_success": {
        "uk": "✅ Доступ активовано!", "ru": "✅ Доступ активирован!", "en": "✅ Access activated!"
    },
    "not_subscribed": {
        "uk": "❌ Не підписані. Підпишіться: ", "ru": "❌ Не подписаны. Подпишитесь: ", "en": "❌ Not subscribed. Subscribe: "
    },
    "access_status": {
        "uk": "✅ Доступ активний, залишилось {days} днів",
        "ru": "✅ Доступ активен, осталось {days} дней",
        "en": "✅ Access active, {days} days left"
    },
    "no_access": {
        "uk": "❌ Немає активної підписки.",
        "ru": "❌ Нет подписки.",
        "en": "❌ No active subscription."
    },
}

user_lang = {}
def lang(user_id): return user_lang.get(user_id, "uk")
def tr(user_id, key): return TEXT[key][lang(user_id)]

# 📩 Webhook обробка (Telegram + CryptoBot)
@fastapi_app.post("/webhook")
async def telegram_and_crypto_webhook(request: Request):
    data = await request.json()

    if "payload" in data:
        payload = data["payload"]
        if ":" in payload:
            uid, key = payload.split(":")
            try:
                uid = int(uid)
                days = TARIFFS[key]["duration_days"]
                add_or_update_user(uid, days)
                logging.info(f"✅ Activated user {uid} for {days} days via webhook.")
            except Exception as e:
                logging.error(f"❌ Webhook error: {e}")
        return {"ok": True}

    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

# 🟢 /start
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(name, callback_data=f"lang:{code}")] for code, name in LANGUAGES.items()]
    await update.message.reply_text(TEXT["choose_lang"]["uk"], reply_markup=InlineKeyboardMarkup(kb))

# ❔ /help
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(TEXT["commands_list"][lang(uid)])

# 📊 /myaccess
async def myaccess_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    row = get_user_profile(uid)
    if row:
        days = (datetime.datetime.fromisoformat(row[1]) - datetime.datetime.now()).days
        await update.message.reply_text(tr(uid, "access_status").format(days=days))
    else:
        await update.message.reply_text(tr(uid, "no_access"))

# 👑 /admin
async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("⛔️ Access denied.")
        return

    text = update.message.text
    users = get_all_users()
    active, inactive = 0, 0
    now = datetime.datetime.now()

    for _, exp in users:
        dt = datetime.datetime.fromisoformat(exp)
        (active if dt > now else inactive) += 1

    msg = f"👥 Users: {len(users)}\n✅ Active: {active}\n❌ Inactive: {inactive}"

    if " " in text:
        q = text.split(" ", 1)[1].strip()
        for u, exp in users:
            try:
                chat = await ctx.bot.get_chat(u)
                name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
                if q.lower() in name.lower() or q == str(u):
                    left = (datetime.datetime.fromisoformat(exp) - now).days
                    msg += f"\n\n🔍 Found: {name}\nID: {u}\n⏳ Days left: {max(0, left)}"
                    break
            except:
                continue
        else:
            msg += "\n\n🚫 Not found."

    await update.message.reply_text(msg)

# 🔄 Callback handler
async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data.startswith("lang:"):
        code = data.split(":", 1)[1]
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
        payload = {
            "asset": "USDT", "amount": t["amount"],
            "description": f"{t['duration_days']} days",
            "paid_btn_name": "openBot",
            "paid_btn_url": f"https://t.me/{BOT_USERNAME}",
            "payload": f"{uid}:{data}"
        }
        resp = requests.post("https://pay.crypt.bot/api/createInvoice", json=payload,
                             headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN})
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

# 📰 Новини
async def send_news(uid):
    async with httpx.AsyncClient() as cli:
        r = await cli.get("https://cryptopanic.com/api/developer/v2/posts/",
                          params={"auth_token": CRYPTOPANIC_API_KEY, "public": "true", "kind": "news"})
        posts = r.json().get("results", [])[:3]
    msg = "📰 Останні новини:\n" + "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
    await telegram_app.bot.send_message(uid, msg)

# ⏰ Щогодинна перевірка підписок
async def check_expiry(_):
    now = datetime.datetime.now()
    for uid, exp in get_all_users():
        dt = datetime.datetime.fromisoformat(exp)
        if (dt - now).days == 1:
            await telegram_app.bot.send_message(uid, "⚠️ Завтра завершується підписка.")
        if dt < now:
            remove_user(uid)

# 🚀 Запуск FastAPI + Telegram Bot
from uvicorn import Config, Server

async def main():
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_cmd))
    telegram_app.add_handler(CommandHandler("myaccess", myaccess_cmd))
    telegram_app.add_handler(CommandHandler("admin", admin_cmd))
    telegram_app.add_handler(CallbackQueryHandler(handle_cb))
    telegram_app.job_queue.run_repeating(check_expiry, interval=3600)
    await telegram_app.initialize()

    config = Config(fastapi_app, host="0.0.0.0", port=8000, log_level="info")
    server = Server(config)

    await asyncio.gather(
        telegram_app.start(),
        server.serve()
    )

if __name__ == "__main__":
    asyncio.run(main())
