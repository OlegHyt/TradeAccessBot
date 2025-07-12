# config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")

CHANNEL_CHAT_ID = int(os.getenv("CHANNEL_CHAT_ID", "-1006800873578"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/TradeAnalitAcces")

OWNER_ID = int(os.getenv("OWNER_ID", "6800873578"))

CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Тарифи
TARIFFS = {
    "30": {"amount_cents": 599, "days": 30},
    "365": {"amount_cents": 3999, "days": 365},
}
