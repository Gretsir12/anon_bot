from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env файле")
if not BOT_USERNAME:
    raise ValueError("BOT_USERNAME не задан в .env файле")