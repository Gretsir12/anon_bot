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

    try:
        c.execute("ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'text'")
    except sqlite3.OperationalError:
        pass

    # Совладельцы: co_owner_id видит входящие owner_id и может отвечать
    c.execute("""
        CREATE TABLE IF NOT EXISTS co_owners (
            owner_id    INTEGER NOT NULL,
            co_owner_id INTEGER NOT NULL,
            added_at    TEXT NOT NULL,
            PRIMARY KEY (owner_id, co_owner_id)
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
    c.execute("SELECT user_id, username, first_name, last_name, token FROM users WHERE token=?", (token,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3], "token": row[4]}
    return None


def get_user_by_id(user_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, last_name, token FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3], "token": row[4]}
    return None


def get_user_by_username(username: str) -> dict | None:
    clean = username.lstrip("@").lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, last_name FROM users WHERE LOWER(username)=?", (clean,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "last_name": row[3]}
    return None


def get_all_users(limit: int = 100) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, first_name, last_name, created_at FROM users ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "username": r[1], "first_name": r[2], "last_name": r[3], "created_at": r[4]} for r in rows]


# ── Совладельцы ───────────────────────────────────────────

def add_co_owner(owner_id: int, co_owner_id: int) -> bool:
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.first_name, u.last_name, co.added_at
        FROM co_owners co JOIN users u ON co.co_owner_id = u.user_id
        WHERE co.owner_id=?
    """, (owner_id,))
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "username": r[1], "first_name": r[2], "last_name": r[3], "added_at": r[4]} for r in rows]


def get_owned_by(co_owner_id: int) -> list[int]:
    """owner_id-ы, для которых данный пользователь является совладельцем."""
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


# ── Сообщения ─────────────────────────────────────────────

def save_message(
    recipient_id: int,
    sender_id: int | None,
    sender_username: str | None,
    sender_name: str | None,
    text: str,
    message_type: str = "text"
) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO messages (
            recipient_id,
            sender_id,
            sender_username,
            sender_name,
            message_text,
            message_type,
            sent_at
        )
        VALUES (?,?,?,?,?,?,?)
    """, (
        recipient_id,
        sender_id,
        sender_username,
        sender_name,
        text,
        message_type,
        now
    ))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def get_message(msg_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT
            id,
            recipient_id,
            sender_id,
            sender_username,
            sender_name,
            message_text,
            message_type,
            reply_text,
            replied_at,
            sent_at
        FROM messages
        WHERE id=?
    """, (msg_id,))

    row = c.fetchone()
    conn.close()

    if row:
        return {
            "id": row[0],
            "recipient_id": row[1],
            "sender_id": row[2],
            "sender_username": row[3],
            "sender_name": row[4],
            "text": row[5],
            "message_type": row[6],
            "reply_text": row[7],
            "replied_at": row[8],
            "sent_at": row[9],
        }

    return None


def save_reply(msg_id: int, reply_text: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE messages SET reply_text=?, replied_at=? WHERE id=?",
              (reply_text, datetime.now().isoformat(), msg_id))
    conn.commit()
    conn.close()


def get_messages_for_recipient(recipient_id: int, limit: int = 30) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, sender_id, sender_username, sender_name,
           message_text, message_type,
           reply_text, replied_at, sent_at
        FROM messages WHERE recipient_id=?
        ORDER BY sent_at DESC LIMIT ?
    """, (recipient_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0],
        "sender_id": r[1],
        "sender_username": r[2], "sender_name": r[3],
        "text": r[4],
        "message_type": r[5],
        "reply_text": r[6],
        "replied_at": r[7],
        "sent_at": r[8]
     } for r in rows]


def get_sent_by_user(sender_id: int, limit: int = 30) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT m.id, m.recipient_id, u.first_name, u.last_name, u.username,
            m.message_text, m.message_type,
            m.reply_text, m.sent_at
        FROM messages m LEFT JOIN users u ON m.recipient_id = u.user_id
        WHERE m.sender_id=?
        ORDER BY m.sent_at DESC LIMIT ?
    """, (sender_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "recipient_id": r[1],
        "recipient_name": ((r[2] or "") + " " + (r[3] or "")).strip(),
        "recipient_username": r[4],
        "text": r[5],
        "message_type": r[6],
        "reply_text": r[7],
        "sent_at": r[8]
    } for r in rows]


def get_all_messages(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT m.id, m.sender_id, m.sender_username, m.sender_name,
            m.recipient_id, ur.first_name, ur.last_name, ur.username,
            m.message_text, m.message_type,
            m.reply_text, m.sent_at
        FROM messages m LEFT JOIN users ur ON m.recipient_id = ur.user_id
        ORDER BY m.sent_at DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "sender_id": r[1], "sender_username": r[2], "sender_name": r[3],
        "recipient_id": r[4], "recipient_name": ((r[5] or "") + " " + (r[6] or "")).strip(),
        "recipient_username": r[7], "text": r[8],
        "message_type": r[9],
        "reply_text": r[10],
        "sent_at": r[11]
     } for r in rows]