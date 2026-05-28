from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME") 

_raw_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: set[int] = {int(x.strip()) for x in _raw_admins.split(",") if x.strip().isdigit()}

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env файле")
if not BOT_USERNAME:
    raise ValueError("BOT_USERNAME не задан в .env файле")