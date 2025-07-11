import asyncio, datetime, logging, requests, httpx
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from pycoingecko import CoinGeckoAPI
from config import BOT_TOKEN, BOT_USERNAME, TARIFFS, CRYPTO_PAY_TOKEN, CHANNEL_CHAT_ID, CHANNEL_LINK, CRYPTOPANIC_API_KEY, OWNER_ID
from db import add_or_update_user, get_user_profile, get_all_users, remove_user

logging.basicConfig(level=logging.INFO)
fastapi_app = FastAPI()
tg_app = ApplicationBuilder().token(BOT_TOKEN).build()
cg = CoinGeckoAPI()

# … (локализация, tr/lang как раньше) …

@fastapi_app.post("/webhook")
async def webhook(request: Request):
    d = await request.json()
    if payload := d.get("payload"):
        uid, key = payload.split(":")
        try:
            add_or_update_user(int(uid), TARIFFS[key]["duration_days"])
        except Exception: pass
        return {"ok": True}
    upd = Update.de_json(d, tg_app.bot)
    await tg_app.process_update(upd)
    return {"ok": True}

async def start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # кнопки выбора языка…
async def handle_cb(u: Update, ctx:...): 
    # старый код handle_cb
    if data=="admin" and u.from_user.id==OWNER_ID:
        kb=[[InlineKeyboardButton("📤 Рассылка",callback_data="adm_broadcast")],
            [InlineKeyboardButton("📈 Статистика",callback_data="adm_stats")],
            [InlineKeyboardButton("⚙️ Тарифы",callback_data="adm_tariffs")]]
        await q.edit_message_text("Admin panel:",reply_markup=InlineKeyboardMarkup(kb))
    elif data=="adm_stats" and u.from_user.id==OWNER_ID:
        users = get_all_users()
        active = sum((datetime.datetime.fromisoformat(e)>datetime.datetime.now()) for _,e in users)
        await q.edit_message_text(f"👥 Всех: {len(users)}, ✅ Активных: {active}")
    elif data=="adm_broadcast" and u.from_user.id==OWNER_ID:
        await q.edit_message_text("Введите текст рассылки:")
        ctx.user_data["admin_mode"]="broadcast"
    elif update.message and ctx.user_data.get("admin_mode")=="broadcast":
        txt=update.message.text
        for uid,_ in get_all_users():
            await tg_app.bot.send_message(uid, txt)
        ctx.user_data.pop("admin_mode",None)
    elif data=="crypto" and u.from_user.id==OWNER_ID:
        price = cg.get_price(ids="bitcoin", vs_currencies="usd")["bitcoin"]["usd"]
        await q.edit_message_text(f"BTC = ${price}")
    # остальные кнопки…

async def help_cmd(...): ...
async def myaccess(...): await handle_cb(...)
async def check_expiry(_:ContextTypes.DEFAULT_TYPE):
    for uid, exp in get_all_users():
        ...
        await tg_app.bot.send_message(uid, "...")

@fastapi_app.get("/") 
def health(): return {"ok":True}

async def main():
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("myaccess", myaccess))
    tg_app.add_handler(CommandHandler("admin", lambda u,c: c.bot.send_message(u.effective_user.id, "Ок"), filters=lambda m: m.from_user.id==OWNER_ID))
    tg_app.add_handler(CallbackQueryHandler(handle_cb))
    tg_app.job_queue.run_repeating(check_expiry, interval=3600)
    await tg_app.initialize()
    from uvicorn import Config, Server
    server = Server(Config(fastapi_app, host="0.0.0.0", port=8000))
    await asyncio.gather(tg_app.start(), server.serve())

if __name__=="__main__":
    asyncio.run(main())
