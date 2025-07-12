import os
from dotenv import load_dotenv

# 📦 Завантаження змінних середовища з .env
load_dotenv()

# 🤖 Telegram бот
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")  # <-- в .env
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")

# 📢 Канал
CHANNEL_CHAT_ID = int(os.getenv("CHANNEL_CHAT_ID", "-1006800873578"))
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/TradeAnalitAcces")

# 👤 Адмін ID
OWNER_ID = int(os.getenv("OWNER_ID", "6800873578"))

# 📰 CryptoPanic
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")

# 🤖 GPT-4o (OpenAI API)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 💳 Stripe API Key
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")

# 💸 Тарифи з локалізацією назв
TARIFFS = {
    "30d": {
        "amount": 5.99,
        "duration_days": 30,
        "labels": {
            "uk": "💳 5.99 USDT / 30 днів",
            "ru": "💳 5.99 USDT / 30 дней",
            "en": "💳 5.99 USDT / 30 days"
        }
    },
    "365d": {
        "amount": 39.99,
        "duration_days": 365,
        "labels": {
            "uk": "💎 39.99 USDT / 365 днів",
            "ru": "💎 39.99 USDT / 365 дней",
            "en": "💎 39.99 USDT / 365 days"
        }
    }
}
