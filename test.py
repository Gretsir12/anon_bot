import sqlite3
import os

os.makedirs("data", exist_ok=True)
DB_PATH = "data/anonbot.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'text';
""")
