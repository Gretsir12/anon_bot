import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

import database as db
from config import BOT_TOKEN, BOT_USERNAME

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Состояния диалогов
WAITING_ANON_MSG = 1
WAITING_REPLY_TEXT = 2
WAITING_CO_OWNER_ID = 3


# ── Утилиты ───────────────────────────────────────────────

def fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso


def user_display(user) -> str:
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    return name.strip() or str(user.id)


def sender_line(msg: dict) -> str:
    """Строка об отправителе (для владельца/совладельца)."""
    parts = []
    if msg.get("sender_name"):
        parts.append(msg["sender_name"])
    if msg.get("sender_username"):
        parts.append(f"@{msg['sender_username']}")
    if msg.get("sender_id"):
        parts.append(f"id: <code>{msg['sender_id']}</code>")
    return " · ".join(parts) if parts else "неизвестен"


# ── Карточка сообщения (отправляется владельцу/совладельцам) ──

async def send_message_card(bot, owner_id: int, msg_id: int, msg_data: dict):
    """Отправляет красивую карточку входящего анонимного сообщения."""
    text = (
        f"💌 <b>Анонимное сообщение</b>  <code>#{msg_id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{msg_data['text']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 От: {sender_line(msg_data)}\n"
        f"🕐 {fmt_dt(msg_data['sent_at'])}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ Ответить", callback_data=f"reply:{msg_id}:{owner_id}")]
    ])

    # Отправляем владельцу
    try:
        await bot.send_message(owner_id, text, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.warning(f"Не удалось отправить карточку владельцу {owner_id}: {e}")

    # Отправляем всем совладельцам
    for co in db.get_co_owners(owner_id):
        try:
            await bot.send_message(co["user_id"], text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            logger.warning(f"Не удалось отправить карточку совладельцу {co['user_id']}: {e}")


# ── /start ─────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    db.get_or_create_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
    )

    # Deep link — /start <token>
    if args:
        token = args[0]
        recipient = db.get_user_by_token(token)

        if not recipient:
            await update.message.reply_text("❌ Ссылка недействительна или устарела.")
            return ConversationHandler.END

        if recipient["user_id"] == user.id:
            await update.message.reply_text(
                "😅 Нельзя написать самому себе.\n\nПоделись ссылкой с другими!"
            )
            return ConversationHandler.END

        context.user_data["recipient_id"] = recipient["user_id"]
        recipient_name = recipient["first_name"] or "пользователю"

        await update.message.reply_text(
            f"👤 Пишешь анонимно для <b>{recipient_name}</b>\n\n"
            "✍️ Отправь своё сообщение — получатель не узнает, кто ты.\n\n"
            "<i>Только текст. /cancel — отмена.</i>",
            parse_mode="HTML",
        )
        return WAITING_ANON_MSG

    # Обычный старт
    user_data = db.get_or_create_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
    )
    link = f"https://t.me/{BOT_USERNAME}?start={user_data['token']}"

    owned = db.get_owned_channels(user.id)
    owned_info = ""
    if owned:
        owners = [db.get_user_by_id(oid) for oid in owned]
        names = [o["first_name"] for o in owners if o]
        owned_info = f"\n\n👥 Ты совладелец у: <b>{', '.join(names)}</b>"

    await update.message.reply_text(
        f"👋 Привет, <b>{user_display(user)}</b>!\n\n"
        f"🔗 <b>Твоя анонимная ссылка:</b>\n"
        f"<code>{link}</code>\n\n"
        "Поделись ей — люди смогут писать тебе анонимно.\n"
        "Ты видишь, <b>кто</b> написал. Они — нет.\n"
        f"{owned_info}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Скопировать ссылку", switch_inline_query=link)],
            [
                InlineKeyboardButton("👥 Совладельцы", callback_data="coowners:list"),
                InlineKeyboardButton("📬 Сообщения", callback_data=f"inbox:{user.id}"),
            ],
        ]),
    )
    return ConversationHandler.END


# ── Получение анонимного сообщения ─────────────────────────

async def receive_anon_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    recipient_id = context.user_data.get("recipient_id")

    if not recipient_id:
        await update.message.reply_text("Используй /start чтобы начать.")
        return ConversationHandler.END

    msg_id = db.save_message(
        recipient_id=recipient_id,
        sender_id=user.id,
        sender_username=user.username or "",
        sender_name=user_display(user),
        text=text,
    )

    msg_data = db.get_message(msg_id)
    await send_message_card(context.bot, recipient_id, msg_id, msg_data)

    await update.message.reply_text(
        "✅ <b>Сообщение отправлено анонимно!</b>\n\n"
        "Хочешь получать сообщения тоже? /start",
        parse_mode="HTML",
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Ответы на сообщения ────────────────────────────────────

async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажата кнопка «Ответить»."""
    query = update.callback_query
    await query.answer()

    _, msg_id_str, owner_id_str = query.data.split(":")
    msg_id = int(msg_id_str)
    owner_id = int(owner_id_str)
    user_id = query.from_user.id

    if not db.has_access(owner_id, user_id):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    msg = db.get_message(msg_id)
    if not msg:
        await query.answer("Сообщение не найдено.", show_alert=True)
        return

    context.user_data["reply_msg_id"] = msg_id
    context.user_data["reply_sender_id"] = msg["sender_id"]
    context.user_data["reply_owner_id"] = owner_id

    await query.message.reply_text(
        f"↩️ Пишешь ответ на сообщение <code>#{msg_id}</code>:\n"
        f"<i>{msg['text'][:200]}</i>\n\n"
        "Отправь текст ответа. /cancel — отмена.",
        parse_mode="HTML",
    )
    return WAITING_REPLY_TEXT


async def receive_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    reply_text = update.message.text
    msg_id = context.user_data.get("reply_msg_id")
    sender_id = context.user_data.get("reply_sender_id")
    owner_id = context.user_data.get("reply_owner_id")

    if not msg_id:
        await update.message.reply_text("Что-то пошло не так. Попробуй снова.")
        return ConversationHandler.END

    db.save_reply(msg_id, reply_text)

    # Уведомляем отправителя анонимки об ответе
    if sender_id:
        try:
            await context.bot.send_message(
                chat_id=sender_id,
                text=(
                    f"💬 <b>Тебе ответили на анонимное сообщение!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{reply_text}"
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не смог доставить ответ отправителю {sender_id}: {e}")

    await update.message.reply_text(
        "✅ <b>Ответ отправлен!</b>",
        parse_mode="HTML",
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Совладельцы ────────────────────────────────────────────

async def coowners_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    co_owners = db.get_co_owners(user_id)

    if co_owners:
        lines = []
        buttons = []
        for co in co_owners:
            name = ((co["first_name"] or "") + " " + (co["last_name"] or "")).strip() or "—"
            uname = f"@{co['username']}" if co["username"] else "—"
            lines.append(f"• {name} {uname} (<code>{co['user_id']}</code>)")
            buttons.append([InlineKeyboardButton(
                f"❌ Удалить {name}",
                callback_data=f"coowners:remove:{co['user_id']}"
            )])
        text = "👥 <b>Твои совладельцы:</b>\n\n" + "\n".join(lines)
    else:
        text = "👥 <b>Совладельцы:</b>\n\nПока никого нет."
        buttons = []

    buttons.append([InlineKeyboardButton("➕ Добавить совладельца", callback_data="coowners:add")])

    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def coowners_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["adding_co_owner_for"] = query.from_user.id

    await query.message.reply_text(
        "➕ <b>Добавление совладельца</b>\n\n"
        "Попроси человека написать боту /myid — он получит свой ID.\n"
        "Затем пришли сюда этот ID (только цифры).\n\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )
    return WAITING_CO_OWNER_ID


async def receive_co_owner_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.user_data.get("adding_co_owner_for")
    if not owner_id:
        return ConversationHandler.END

    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Введи только числовой ID.")
        return WAITING_CO_OWNER_ID

    co_id = int(text)

    if co_id == owner_id:
        await update.message.reply_text("❌ Нельзя добавить самого себя.")
        return WAITING_CO_OWNER_ID

    co_user = db.get_user_by_id(co_id)
    if not co_user:
        await update.message.reply_text(
            "❌ Пользователь не найден. Убедись, что он уже писал боту (/start)."
        )
        return WAITING_CO_OWNER_ID

    added = db.add_co_owner(owner_id, co_id)
    name = co_user["first_name"] or str(co_id)

    if added:
        # Уведомляем нового совладельца
        try:
            owner_user = db.get_user_by_id(owner_id)
            owner_name = owner_user["first_name"] if owner_user else "кто-то"
            await context.bot.send_message(
                co_id,
                f"✅ <b>{owner_name}</b> добавил тебя как совладельца!\n\n"
                "Теперь ты видишь все анонимные сообщения в его адрес и можешь отвечать на них.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await update.message.reply_text(f"✅ <b>{name}</b> добавлен как совладелец.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"ℹ️ <b>{name}</b> уже является совладельцем.", parse_mode="HTML")

    context.user_data.clear()
    return ConversationHandler.END


async def coowners_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    owner_id = query.from_user.id
    co_id = int(query.data.split(":")[2])

    removed = db.remove_co_owner(owner_id, co_id)
    co_user = db.get_user_by_id(co_id)
    name = co_user["first_name"] if co_user else str(co_id)

    if removed:
        try:
            await context.bot.send_message(
                co_id,
                "ℹ️ Тебя удалили из совладельцев анонимной страницы.",
            )
        except Exception:
            pass
        await query.edit_message_text(f"✅ <b>{name}</b> удалён из совладельцев.", parse_mode="HTML")
    else:
        await query.edit_message_text("❌ Не найден.", parse_mode="HTML")


# ── Входящие ───────────────────────────────────────────────

async def inbox_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    owner_id = int(query.data.split(":")[1])
    user_id = query.from_user.id

    if not db.has_access(owner_id, user_id):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    messages = db.get_messages_for_owner(owner_id, limit=20)
    if not messages:
        await query.edit_message_text("📭 Сообщений пока нет.")
        return

    lines = [f"📬 <b>Последние сообщения ({len(messages)}):</b>\n"]
    for m in messages:
        replied = " ✅" if m["reply_text"] else ""
        lines.append(
            f"<code>#{m['id']}</code>{replied} · {fmt_dt(m['sent_at'])}\n"
            f"👤 {sender_line(m)}\n"
            f"💬 {m['text'][:120]}{'…' if len(m['text']) > 120 else ''}\n"
        )

    chunk = "\n".join(lines)
    if len(chunk) > 4000:
        chunk = chunk[:4000] + "\n…"

    await query.edit_message_text(chunk, parse_mode="HTML")


# ── /myid ─────────────────────────────────────────────────

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        f"🪪 Твой Telegram ID: <code>{uid}</code>\n\n"
        "Скопируй и отправь его тому, кто хочет добавить тебя как совладельца.",
        parse_mode="HTML",
    )


# ── /cancel ────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


# ── /help ─────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Команды:</b>\n\n"
        "/start — главное меню и твоя ссылка\n"
        "/myid — узнать свой Telegram ID\n"
        "/cancel — отменить текущее действие\n"
        "/help — эта справка",
        parse_mode="HTML",
    )


# ── Запуск ─────────────────────────────────────────────────

def main():
    db.init_db()
    logger.info("БД инициализирована")

    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler: анонимное сообщение + ответ + добавление совладельца
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(reply_callback, pattern=r"^reply:"),
            CallbackQueryHandler(coowners_add_callback, pattern=r"^coowners:add$"),
        ],
        states={
            WAITING_ANON_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_anon_message),
            ],
            WAITING_REPLY_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_reply),
            ],
            WAITING_CO_OWNER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_co_owner_id),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(coowners_list_callback, pattern=r"^coowners:list$"))
    app.add_handler(CallbackQueryHandler(coowners_remove_callback, pattern=r"^coowners:remove:"))
    app.add_handler(CallbackQueryHandler(inbox_callback, pattern=r"^inbox:"))

    logger.info("Бот запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()