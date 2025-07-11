# bot.py

import asyncio
import datetime
import httpx
import logging
import requests
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from config import (
    BOT_TOKEN, TARIFFS, CRYPTO_PAY_TOKEN, CHANNEL_LINK, CHANNEL_CHAT_ID,
    OWNER_ID, BOT_USERNAME, CRYPTOPANIC_API_KEY
)
from db import add_or_update_user, get_user_profile, get_all_users, remove_user

logging.basicConfig(level=logging.INFO)

# 🌐 Підтримувані мови
LANGUAGES = {
    "uk": "Українська",
    "ru": "Русский",
    "en": "English"
}

# 📦 Локалізація
TEXT = {
    "choose_lang": {
        "uk": "Оберіть мову:",
        "ru": "Выберите язык:",
        "en": "Choose your language:"
    },
    "main_menu": {
        "uk": "Вітаю, {name}!\nОберіть опцію:",
        "ru": "Привіт, {name}!\nВыберите опцию:",
        "en": "Welcome, {name}!\nChoose an option:"
    },
    "buttons": {
        "access": {"uk": "📊 Мій доступ", "ru": "📊 Мой доступ", "en": "📊 My Access"},
        "subscribe": {"uk": "🔁 Продовжити підписку", "ru": "🔁 Продлить подписку", "en": "🔁 Renew Subscription"},
        "news": {"uk": "📰 Новини", "ru": "📰 Новости", "en": "📰 News"},
        "commands": {"uk": "📌 Команди", "ru": "📌 Команды", "en": "📌 Commands"},
    },
    "commands_list": {
        "uk": "📌 Команди:\n/start — стартове меню\n/myaccess — мій доступ\n/profile — особистий кабінет\n/admin — адмін-панель\n/help — допомога",
        "ru": "📌 Команды:\n/start — главное меню\n/myaccess — мой доступ\n/profile — личный кабинет\n/admin — админка\n/help — помощь",
        "en": "📌 Commands:\n/start — main menu\n/myaccess — my access\n/profile — profile\n/admin — admin panel\n/help — help"
    },
    "choose_tariff": {
        "uk": "Оберіть тариф:",
        "ru": "Выберите тариф:",
        "en": "Choose a tariff:"
    },
    "pay_success": {
        "uk": "✅ Доступ активовано!",
        "ru": "✅ Доступ активирован!",
        "en": "✅ Access activated!"
    },
    "not_subscribed": {
        "uk": "❌ Ви не підписані на канал. Підпишіться: ",
        "ru": "❌ Вы не подписаны на канал. Подпишитесь: ",
        "en": "❌ You are not subscribed. Subscribe: "
    },
    "access_status": {
        "uk": "✅ Доступ активний\nЗалишилось днів: {days}",
        "ru": "✅ Доступ активен\nОсталось дней: {days}",
        "en": "✅ Access active\nDays left: {days}"
    },
    "no_access": {
        "uk": "❌ У вас немає активної підписки.",
        "ru": "❌ У вас нет активной подписки.",
        "en": "❌ You have no active subscription."
    }
}

# Зберігання мов користувачів
user_languages = {}

def get_lang(user_id):
    return user_languages.get(user_id, "uk")

def t(user_id, key):
    lang = get_lang(user_id)
    return TEXT[key][lang]

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [[InlineKeyboardButton(name, callback_data=f"lang:{code}")] for code, name in LANGUAGES.items()]
    await update.message.reply_text(TEXT["choose_lang"]["uk"], reply_markup=InlineKeyboardMarkup(keyboard))

# Обробка кнопок
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("lang:"):
        lang = data.split(":")[1]
        user_languages[user_id] = lang
        name = query.from_user.first_name
        keyboard = [
            [InlineKeyboardButton(TEXT["buttons"]["access"][lang], callback_data="access")],
            [InlineKeyboardButton(TEXT["buttons"]["subscribe"][lang], callback_data="subscribe")],
            [InlineKeyboardButton(TEXT["buttons"]["news"][lang], callback_data="news")],
            [InlineKeyboardButton(TEXT["buttons"]["commands"][lang], callback_data="commands")]
        ]
        await query.edit_message_text(TEXT["main_menu"][lang].format(name=name), reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "subscribe":
        lang = get_lang(user_id)
        keyboard = [
            [InlineKeyboardButton(tariff["labels"][lang], callback_data=key)]
            for key, tariff in TARIFFS.items()
        ]
        await query.edit_message_text(TEXT["choose_tariff"][lang], reply_markup=InlineKeyboardMarkup(keyboard))

    elif data in TARIFFS:
        tariff = TARIFFS[data]
        amount = tariff["amount"]
        days = tariff["duration_days"]
        context.user_data["tariff_days"] = days

        payload = {
            "asset": "USDT",
            "amount": amount,
            "description": f"{days} days access",
            "paid_btn_name": "openBot",
            "paid_btn_url": f"https://t.me/{BOT_USERNAME}",
            "payload": f"{user_id}:{data}"
        }
        headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
        response = requests.post("https://pay.crypt.bot/api/createInvoice", json=payload, headers=headers)
        result = response.json()
        if result.get("ok"):
            pay_url = result["result"]["pay_url"]
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Я підписався", callback_data="check_sub")]])
            await query.edit_message_text(f"🔗 Оплатіть за посиланням:\n{pay_url}", reply_markup=markup)
        else:
            await query.edit_message_text("❌ Помилка створення рахунку")

    elif data == "check_sub":
        try:
            member = await context.bot.get_chat_member(chat_id=CHANNEL_CHAT_ID, user_id=user_id)
            if member.status in ["member", "administrator", "creator"]:
                days = context.user_data.get("tariff_days", 30)
                add_or_update_user(user_id, days)
                await query.edit_message_text(t(user_id, "pay_success"))
            else:
                raise Exception("Not subscribed")
        except:
            await query.edit_message_text(t(user_id, "not_subscribed") + CHANNEL_LINK)

    elif data == "access":
        user_data = get_user_profile(user_id)
        if user_data:
            expires = user_data[1]
            days_left = (datetime.datetime.fromisoformat(expires) - datetime.datetime.now()).days
            await query.edit_message_text(t(user_id, "access_status").format(days=days_left))
        else:
            await query.edit_message_text(t(user_id, "no_access"))

    elif data == "news":
        await send_news(context, user_id)

    elif data == "commands":
        await query.edit_message_text(TEXT["commands_list"][get_lang(user_id)])


# Надсилання новин
async def send_news(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    url = "https://cryptopanic.com/api/developer/v2/posts/"
    params = {"auth_token": CRYPTOPANIC_API_KEY, "public": "true", "kind": "news"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        data = resp.json()
        posts = data.get("results", [])[:3]
        message = "📰 *Останні новини:*\n\n" + "\n".join(
            [f"{i+1}. [{p['title']}]({p['url']})" for i, p in enumerate(posts)]
        )
        await context.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown")

# /myaccess
async def myaccess_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_buttons(update, context)

# Автосповіщення
async def check_expiry(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now()
    for uid, expires in get_all_users():
        exp_dt = datetime.datetime.fromisoformat(expires)
        if (exp_dt - now).days == 1:
            try:
                await context.bot.send_message(chat_id=uid, text="⚠️ Завтра завершується підписка!")
            except:
                pass
        if exp_dt < now:
            remove_user(uid)

# Запуск бота
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myaccess", myaccess_command))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.job_queue.run_repeating(check_expiry, interval=3600)
    print("✅ Bot started")
    app.run_polling()
