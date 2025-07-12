# db.py
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            usage INTEGER DEFAULT 0,
            expires TEXT,
            lang TEXT DEFAULT 'ua',
            coins TEXT DEFAULT 'BTCUSDT,ETHUSDT',
            referrals INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS gpt_log (
            user_id INTEGER,
            question TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)
