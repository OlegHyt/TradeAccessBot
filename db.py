import sqlite3
from datetime import datetime, timedelta

def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    # Створення таблиці, якщо не існує
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            access_until TEXT,
            language TEXT DEFAULT 'ua'
        )
    ''')
    conn.commit()
    conn.close()

def add_or_update_user(user_id: int, days: int):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    expires = datetime.now() + timedelta(days=days)
    cursor.execute('''
        INSERT INTO users (user_id, access_until)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET access_until=excluded.access_until
    ''', (user_id, expires.isoformat()))
    conn.commit()
    conn.close()

def get_user_profile(user_id: int):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, access_until FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_all_users():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, access_until FROM users")
    results = cursor.fetchall()
    conn.close()
    return results

def remove_user(user_id: int):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def set_language(user_id: int, lang: str):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()
    conn.close()

def get_language(user_id: int):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "ua"

# Ініціалізація при запуску
init_db()
