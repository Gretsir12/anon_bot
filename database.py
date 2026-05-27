import sqlite3
import uuid
import os
from datetime import datetime

os.makedirs("data", exist_ok=True)
DB_PATH = "data/anonbot.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            token       TEXT UNIQUE NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)

    # direction: 'in' = анонимка получена, 'out' = анонимка отправлена, 'reply' = ответ владельца
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id     INTEGER NOT NULL,
            sender_id        INTEGER,
            sender_username  TEXT,
            sender_name      TEXT,
            message_text     TEXT NOT NULL,
            reply_text       TEXT,
            replied_at       TEXT,
            sent_at          TEXT NOT NULL,
            FOREIGN KEY (recipient_id) REFERENCES users(user_id)
        )
    """)

    conn.commit()
    conn.close()


# ── Пользователи ──────────────────────────────────────────

def get_or_create_user(user_id: int, username: str, first_name: str, last_name: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        c.execute(
            "UPDATE users SET username=?, first_name=?, last_name=? WHERE user_id=?",
            (username, first_name, last_name, user_id),
        )
        token = row[0]
    else:
        token = str(uuid.uuid4()).replace("-", "")[:16]
        now = datetime.now().isoformat()
        c.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, token, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, username, first_name, last_name, token, now),
        )
    conn.commit()
    conn.close()
    return {"user_id": user_id, "token": token}


def get_user_by_token(token: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, first_name, last_name, token FROM users WHERE token=?", (token,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3], "token": row[4]}
    return None


def get_user_by_id(user_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, first_name, last_name, token FROM users WHERE user_id=?", (user_id,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3], "token": row[4]}
    return None


def get_user_by_username(username: str) -> dict | None:
    """Поиск без учёта регистра, с @ или без."""
    clean = username.lstrip("@").lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, first_name, last_name FROM users WHERE LOWER(username)=?", (clean,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3]}
    return None


def get_all_users(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, first_name, last_name, created_at FROM users ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "username": r[1], "first_name": r[2], "last_name": r[3], "created_at": r[4]} for r in rows]


# ── Сообщения ─────────────────────────────────────────────

def save_message(recipient_id: int, sender_id: int | None, sender_username: str | None,
                 sender_name: str | None, text: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO messages (recipient_id, sender_id, sender_username, sender_name, message_text, sent_at)
        VALUES (?,?,?,?,?,?)
    """, (recipient_id, sender_id, sender_username, sender_name, text, now))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def get_message(msg_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, recipient_id, sender_id, sender_username, sender_name,
               message_text, reply_text, replied_at, sent_at
        FROM messages WHERE id=?
    """, (msg_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0], "recipient_id": row[1], "sender_id": row[2],
            "sender_username": row[3], "sender_name": row[4], "text": row[5],
            "reply_text": row[6], "replied_at": row[7], "sent_at": row[8],
        }
    return None


def save_reply(msg_id: int, reply_text: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE messages SET reply_text=?, replied_at=? WHERE id=?",
        (reply_text, datetime.now().isoformat(), msg_id),
    )
    conn.commit()
    conn.close()


def get_messages_for_recipient(recipient_id: int, limit: int = 30) -> list[dict]:
    """Входящие анонимки для данного получателя."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, sender_id, sender_username, sender_name,
               message_text, reply_text, replied_at, sent_at
        FROM messages WHERE recipient_id=?
        ORDER BY sent_at DESC LIMIT ?
    """, (recipient_id, limit))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "sender_id": r[1], "sender_username": r[2], "sender_name": r[3],
            "text": r[4], "reply_text": r[5], "replied_at": r[6], "sent_at": r[7],
        }
        for r in rows
    ]


def get_sent_by_user(sender_id: int, limit: int = 30) -> list[dict]:
    """Анонимки, отправленные данным пользователем."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT m.id, m.recipient_id, u.first_name, u.last_name, u.username,
               m.message_text, m.reply_text, m.sent_at
        FROM messages m
        LEFT JOIN users u ON m.recipient_id = u.user_id
        WHERE m.sender_id=?
        ORDER BY m.sent_at DESC LIMIT ?
    """, (sender_id, limit))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "recipient_id": r[1],
            "recipient_name": ((r[2] or "") + " " + (r[3] or "")).strip(),
            "recipient_username": r[4],
            "text": r[5], "reply_text": r[6], "sent_at": r[7],
        }
        for r in rows
    ]


def get_all_messages(limit: int = 50) -> list[dict]:
    """Все сообщения для панели админа."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT
            m.id,
            m.sender_id, m.sender_username, m.sender_name,
            m.recipient_id,
            ur.first_name, ur.last_name, ur.username,
            m.message_text, m.reply_text, m.sent_at
        FROM messages m
        LEFT JOIN users ur ON m.recipient_id = ur.user_id
        ORDER BY m.sent_at DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "sender_id": r[1], "sender_username": r[2], "sender_name": r[3],
            "recipient_id": r[4],
            "recipient_name": ((r[5] or "") + " " + (r[6] or "")).strip(),
            "recipient_username": r[7],
            "text": r[8], "reply_text": r[9], "sent_at": r[10],
        }
        for r in rows
    ]