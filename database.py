import sqlite3
import uuid
from datetime import datetime

DB_PATH = "anonbot.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Пользователи и их токены
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

    # Совладельцы: user_id владельца → список co-owner user_id
    c.execute("""
        CREATE TABLE IF NOT EXISTS co_owners (
            owner_id    INTEGER NOT NULL,
            co_owner_id INTEGER NOT NULL,
            added_at    TEXT NOT NULL,
            PRIMARY KEY (owner_id, co_owner_id)
        )
    """)

    # Сообщения
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
        "SELECT user_id, username, first_name, last_name, token FROM users WHERE token=?",
        (token,),
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
        "SELECT user_id, username, first_name, last_name, token FROM users WHERE user_id=?",
        (user_id,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3], "token": row[4]}
    return None


# ── Совладельцы ───────────────────────────────────────────

def add_co_owner(owner_id: int, co_owner_id: int) -> bool:
    """Добавить совладельца. Вернуть False если уже есть."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM co_owners WHERE owner_id=? AND co_owner_id=?", (owner_id, co_owner_id))
    if c.fetchone():
        conn.close()
        return False
    c.execute(
        "INSERT INTO co_owners (owner_id, co_owner_id, added_at) VALUES (?,?,?)",
        (owner_id, co_owner_id, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return True


def remove_co_owner(owner_id: int, co_owner_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM co_owners WHERE owner_id=? AND co_owner_id=?", (owner_id, co_owner_id))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_co_owners(owner_id: int) -> list[dict]:
    """Список совладельцев данного владельца."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.first_name, u.last_name, co.added_at
        FROM co_owners co
        JOIN users u ON co.co_owner_id = u.user_id
        WHERE co.owner_id = ?
    """, (owner_id,))
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "username": r[1], "first_name": r[2], "last_name": r[3], "added_at": r[4]} for r in rows]


def get_owned_channels(co_owner_id: int) -> list[int]:
    """Чьим совладельцем является данный пользователь (список owner_id)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT owner_id FROM co_owners WHERE co_owner_id=?", (co_owner_id,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def is_co_owner(owner_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM co_owners WHERE owner_id=? AND co_owner_id=?", (owner_id, user_id))
    result = c.fetchone() is not None
    conn.close()
    return result


def has_access(owner_id: int, user_id: int) -> bool:
    """Есть ли у user_id доступ к сообщениям owner_id (сам или совладелец)."""
    return owner_id == user_id or is_co_owner(owner_id, user_id)


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


def get_messages_for_owner(recipient_id: int, limit: int = 50) -> list[dict]:
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