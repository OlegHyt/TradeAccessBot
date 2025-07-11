import asyncio
import datetime
import logging
import requests
import httpx
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from config import (
    BOT_TOKEN, BOT_USERNAME, TARIFFS,
    CRYPTO_PAY_TOKEN, CHANNEL_CHAT_ID, CHANNEL_LINK,
    CRYPTOPANIC_API_KEY
)
from db import add_or_update_user, get_user_profile, get_all_users, remove_user

# 👤 Власник бота
OWNER_ID = 6800873578

logging.basicConfig(level=logging.INFO)

fastapi_app = FastAPI()
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

# 🌐 Локалізація
LANGUAGES = {"uk": "Українська", "ru": "Русский", "en": "English"}

TEXT = {
    "choose_lang": {"uk": "Оберіть мову:", "ru": "Выберите язык:", "en": "Choose your language:"},
    "main_menu": {"uk": "Вітаю, {name}!\nОберіть:", "ru": "Привет, {name}!\nВыберите:", "en": "Welcome, {name}!\nChoose:"},
    "buttons": {
        "access": {"uk": "📊 Мій доступ", "ru": "📊 Мой доступ", "en": "📊 My Access"},
        "subscribe": {"uk": "🔁 Продовжити підписку", "ru": "🔁 Продлить подписку", "en": "🔁 Renew Subscription"},
        "news": {"uk": "📰 Новини", "ru": "📰 Новости", "en": "📰 News"},
        "commands": {"uk": "📌 Команди", "ru": "📌 Команды", "en": "📌 Commands"},
    },
    "commands_list": {
        "uk": "/start — запуск\n/myaccess — мій доступ\n/help — список команд\n/admin — адмін-панель",
        "ru": "/start — запуск\n/myaccess — мой доступ\n/help — список команд\n/admin — админ-панель",
        "en": "/start — start\n/myaccess — my access\n/help — command list\n/admin — admin panel"
    },
    "choose_tariff": {"uk": "Оберіть тариф:", "ru": "Выберите тариф:", "en": "Choose tariff:"},
    "pay_success": {"uk": "✅ Доступ активовано!", "ru": "✅ Доступ активирован!", "en": "✅ Access activated!"},
    "not_subscribed": {"uk": "❌ Не підписані. Підпишіться: ", "ru": "❌ Не подписаны. Подпишитесь: ", "en": "❌ Not subscribed. Subscribe: "},
    "access_status": {"uk": "✅ Доступ активний, залишилось {days} днів", "ru": "✅ Доступ активен, осталось {days} дней", "en": "✅ Access active, {days} days left"},
    "no_access": {"uk": "❌ Немає активної підписки.", "ru": "❌ Нет подписки.", "en": "❌ No active subscription."},
}

user_lang = {}
def lang(user_id): return user_lang.get(user_id, "uk")
def tr(user_id, key): return TEXT[key][lang(user_id)]

# ✅ Webhook
@fastapi_app.post("/webhook")
async def telegram_and_crypto_webhook(request: Request):
    data = await request.json()
    if "payload" in data:  # CryptoBot
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

# 📦 Callback обробник
async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data.startswith("lang:"):
        code = data.split(":", 1)[1]
        user_lang[uid] = code
        name = q.from_user.first_name
        kb = [[InlineKeyboardButton(TEXT["buttons"][k][code], callback_data=k)] for k in TEXT["buttons"]]
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

# 📊 /myaccess
async def myaccess_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    row = get_user_profile(uid)
    if row:
        days = (datetime.datetime.fromisoformat(row[1]) - datetime.datetime.now()).days
        await update.message.reply_text(TEXT["access_status"][lang(uid)].format(days=days))
    else:
        await update.message.reply_text(TEXT["no_access"][lang(uid)])

# 🆘 /help
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(TEXT["commands_list"][lang(uid)])

# 👨‍💼 /admin
async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        return await update.message.reply_text("❌ Доступ заборонено.")
    total = len(get_all_users())
    active = sum((datetime.datetime.fromisoformat(exp) > datetime.datetime.now()) for uid, exp in get_all_users())
    inactive = total - active
    await update.message.reply_text(f"👥 Users: {total}\n✅ Active: {active}\n❌ Inactive: {inactive}\n🔍 Надішли ID або ім'я для пошуку:")

# 🔍 Обробка пошуку користувача
async def search_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    query = update.message.text.lower()
    for uid, exp in get_all_users():
        prof = get_user_profile(uid)
        if prof and (query in str(uid) or query in prof[2].lower()):  # name
            days = (datetime.datetime.fromisoformat(prof[1]) - datetime.datetime.now()).days
            return await update.message.reply_text(f"👤 {prof[2]} (ID: {uid})\n📅 Днів залишилось: {days}")
    await update.message.reply_text("❌ Користувача не знайдено.")

# 📰 Новини
async def send_news(uid):
    async with httpx.AsyncClient() as cli:
        r = await cli.get("https://cryptopanic.com/api/developer/v2/posts/",
                          params={"auth_token": CRYPTOPANIC_API_KEY, "public": "true", "kind": "news"})
        posts = r.json().get("results", [])[:3]
    msg = "📰 Останні новини:\n" + "\n".join(f"{i+1}. {p['title']}" for i, p in enumerate(posts))
    await telegram_app.bot.send_message(uid, msg)

# ⏰ Перевірка підписки
async def check_expiry(_):
    now = datetime.datetime.now()
    for uid, exp in get_all_users():
        dt = datetime.datetime.fromisoformat(exp)
        if (dt - now).days == 1:
            await telegram_app.bot.send_message(uid, "⚠️ Завтра завершується підписка.")
        if dt < now:
            remove_user(uid)

# 🚀 main
from uvicorn import Config, Server

async def main():
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("myaccess", myaccess_cmd))
    telegram_app.add_handler(CommandHandler("help", help_cmd))
    telegram_app.add_handler(CommandHandler("admin", admin_cmd))
    telegram_app.add_handler(CallbackQueryHandler(handle_cb))
    telegram_app.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=OWNER_ID), search_user))
    telegram_app.job_queue.run_repeating(check_expiry, interval=3600)
    await telegram_app.initialize()

    config = Config(fastapi_app, host="0.0.0.0", port=8000)
    server = Server(config)

    await asyncio.gather(telegram_app.start(), server.serve())

if __name__ == "__main__":
    asyncio.run(main())
