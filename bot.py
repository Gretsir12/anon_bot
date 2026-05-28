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
from config import BOT_TOKEN, BOT_USERNAME, ADMIN_IDS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_ANON_MSG  = 1
WAITING_REPLY_TEXT = 2


# ── Утилиты ───────────────────────────────────────────────

def fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso


def user_display(user) -> str:
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    return name.strip() or str(user.id)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def sender_line_admin(msg: dict) -> str:
    """Полная строка об отправителе — только для админов."""
    parts = []
    if msg.get("sender_name"):
        parts.append(msg["sender_name"])
    if msg.get("sender_username"):
        parts.append(f"@{msg['sender_username']}")
    if msg.get("sender_id"):
        parts.append(f"id: <code>{msg['sender_id']}</code>")
    return " · ".join(parts) if parts else "неизвестен"


def chunk_text(text: str, limit: int = 4000) -> list[str]:
    """Разбить длинный текст на части для отправки в Telegram."""
    parts = []
    while len(text) > limit:
        cut = text[:limit].rfind("\n")
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:]
    parts.append(text)
    return parts


# ── Карточки сообщений ────────────────────────────────────

async def deliver_to_recipient(bot, recipient_id: int, msg_id: int, msg_data: dict):
    """
    Получателю — только анонимная карточка без данных отправителя.
    Кнопка «Ответить» привязана к получателю (он и есть owner ответа).
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Ответить", callback_data=f"reply:{msg_id}:{recipient_id}")]
    ])
    card = (
        f"💬 <b>У тебя новое анонимное сообщение!</b>\n\n"
        f"{msg_data['text']}\n\n"
        f"<i>⬅️ Свайпни для ответа.</i>"
    )
    try:
        await bot.send_message(recipient_id, card, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.warning(f"Карточка → {recipient_id}: {e}")


async def deliver_to_admins(bot, msg_id: int, msg_data: dict):
    """
    Админам — та же карточка + отдельное сообщение с деаноном.
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Ответить", callback_data=f"reply:{msg_id}:{msg_data['recipient_id']}")]
    ])
    card = (
        f"💬 <b>Новое анонимное сообщение</b>  <code>#{msg_id}</code>\n\n"
        f"{msg_data['text']}\n\n"
        f"<i>⬅️ Свайпни для ответа.</i>"
    )
    deanon = (
        f"🕵️ <b>Деанон  #{msg_id}</b>\n"
        f"👤 От: {sender_line_admin(msg_data)}\n"
        f"📨 Кому: {msg_data.get('recipient_name', '')} "
        f"(id: <code>{msg_data['recipient_id']}</code>)\n"
        f"🕐 {fmt_dt(msg_data['sent_at'])}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, card, parse_mode="HTML", reply_markup=keyboard)
            await bot.send_message(admin_id, deanon, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Деанон → admin {admin_id}: {e}")


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
        context.user_data["recipient_name"] = recipient["first_name"] or "пользователю"

        await update.message.reply_text(
            f"👤 Пишешь анонимно для <b>{context.user_data['recipient_name']}</b>\n\n"
            "✍️ Отправь своё сообщение — получатель не узнает, кто ты.\n\n"
            "<i>Только текст. /cancel — отмена.</i>",
            parse_mode="HTML",
        )
        return WAITING_ANON_MSG

    # Обычный старт — показываем ссылку
    user_data = db.get_or_create_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
    )
    link = f"https://t.me/{BOT_USERNAME}?start={user_data['token']}"

    await update.message.reply_text(
        f"Начни получать анонимные сообщения прямо сейчас 🚀\n\n"
        f"Твоя ссылка 👇\n"
        f"<code>{link}</code>\n"
        f"Размести эту ссылку ☝️ в описании профиля Telegram/TikTok/Instagram, "
        f"чтобы начать получать анонимные сообщения 💬",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Скопировать ссылку", switch_inline_query=link)],
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

    recipient_user = db.get_user_by_id(recipient_id)

    msg_id = db.save_message(
        recipient_id=recipient_id,
        sender_id=user.id,
        sender_username=user.username or "",
        sender_name=user_display(user),
        text=text,
    )

    msg_data = db.get_message(msg_id)
    # Добавляем имя получателя для деанона
    msg_data["recipient_name"] = (
        ((recipient_user["first_name"] or "") + " " + (recipient_user["last_name"] or "")).strip()
        if recipient_user else ""
    )

    # Получателю — без деанона
    await deliver_to_recipient(context.bot, recipient_id, msg_id, msg_data)
    # Админам — с деаноном
    await deliver_to_admins(context.bot, msg_id, msg_data)

    await update.message.reply_text(
        "✅ <b>Сообщение отправлено анонимно!</b>\n\n"
        "Хочешь получать сообщения тоже? /start",
        parse_mode="HTML",
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Ответы на сообщения ────────────────────────────────────

async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    msg_id = int(parts[1])
    recipient_id = int(parts[2])
    user_id = query.from_user.id

    # Ответить может только получатель или админ
    if user_id != recipient_id and not is_admin(user_id):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    msg = db.get_message(msg_id)
    if not msg:
        await query.answer("Сообщение не найдено.", show_alert=True)
        return

    context.user_data["reply_msg_id"] = msg_id
    context.user_data["reply_sender_id"] = msg["sender_id"]
    context.user_data["reply_recipient_id"] = recipient_id

    await query.message.reply_text(
        f"↩️ Отвечаешь на сообщение <code>#{msg_id}</code>:\n"
        f"<i>{msg['text'][:200]}</i>\n\n"
        "Напиши свой ответ. /cancel — отмена.",
        parse_mode="HTML",
    )
    return WAITING_REPLY_TEXT


async def receive_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_text = update.message.text
    msg_id = context.user_data.get("reply_msg_id")
    sender_id = context.user_data.get("reply_sender_id")

    if not msg_id:
        await update.message.reply_text("Что-то пошло не так. Попробуй снова.")
        return ConversationHandler.END

    db.save_reply(msg_id, reply_text)

    if sender_id:
        try:
            await context.bot.send_message(
                chat_id=sender_id,
                text=f"💬 <b>Тебе ответили на анонимное сообщение!</b>\n\n{reply_text}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Не смог доставить ответ {sender_id}: {e}")

    await update.message.reply_text("✅ <b>Ответ отправлен!</b>", parse_mode="HTML")
    context.user_data.clear()
    return ConversationHandler.END


# ── Админ-команды ─────────────────────────────────────────

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /logs @username — вся переписка пользователя (входящие + исходящие).
    /logs — последние 30 сообщений по всем пользователям.
    """
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    # Без аргумента — общий лог
    if not context.args:
        messages = db.get_all_messages(limit=30)
        if not messages:
            await update.message.reply_text("📭 Сообщений пока нет.")
            return

        lines = ["📋 <b>Последние 30 сообщений:</b>\n"]
        for m in messages:
            sender = f"@{m['sender_username']}" if m["sender_username"] else m["sender_name"] or "?"
            recip = f"@{m['recipient_username']}" if m["recipient_username"] else m["recipient_name"] or "?"
            replied = " ✅" if m["reply_text"] else ""
            lines.append(
                f"<code>#{m['id']}</code>{replied}  {fmt_dt(m['sent_at'])}\n"
                f"  От: {sender} (id <code>{m['sender_id']}</code>)\n"
                f"  Кому: {recip} (id <code>{m['recipient_id']}</code>)\n"
                f"  💬 {m['text'][:100]}{'…' if len(m['text'])>100 else ''}\n"
            )

        full = "\n".join(lines)
        for part in chunk_text(full):
            await update.message.reply_text(part, parse_mode="HTML")
        return

    # С аргументом — лог конкретного пользователя
    query_arg = context.args[0]
    target = None

    if query_arg.lstrip("@").isdigit():
        target = db.get_user_by_id(int(query_arg.lstrip("@")))
    else:
        target = db.get_user_by_username(query_arg)

    if not target:
        await update.message.reply_text(
            "❌ Пользователь не найден.\n"
            "Убедись что он уже писал боту, и передай точный @username или числовой id."
        )
        return

    tid = target["user_id"]
    tname = ((target["first_name"] or "") + " " + (target["last_name"] or "")).strip() or str(tid)
    tuname = f"@{target['username']}" if target.get("username") else "—"

    incoming = db.get_messages_for_recipient(tid, limit=30)
    outgoing = db.get_sent_by_user(tid, limit=30)

    lines = [
        f"👤 <b>{tname}</b>  {tuname}  id: <code>{tid}</code>\n",
    ]

    lines.append(f"📥 <b>Входящие ({len(incoming)}):</b>\n")
    if incoming:
        for m in incoming:
            replied = " ✅" if m["reply_text"] else ""
            lines.append(
                f"  <code>#{m['id']}</code>{replied}  {fmt_dt(m['sent_at'])}\n"
                f"  От: {sender_line_admin(m)}\n"
                f"  💬 {m['text'][:120]}{'…' if len(m['text'])>120 else ''}\n"
                + (f"  ↩️ Ответ: {m['reply_text'][:80]}{'…' if len(m['reply_text'])>80 else ''}\n" if m["reply_text"] else "")
            )
    else:
        lines.append("  пусто\n")

    lines.append(f"\n📤 <b>Исходящие ({len(outgoing)}):</b>\n")
    if outgoing:
        for m in outgoing:
            recip = f"@{m['recipient_username']}" if m["recipient_username"] else m["recipient_name"] or "?"
            lines.append(
                f"  <code>#{m['id']}</code>  {fmt_dt(m['sent_at'])}\n"
                f"  Кому: {recip} (id <code>{m['recipient_id']}</code>)\n"
                f"  💬 {m['text'][:120]}{'…' if len(m['text'])>120 else ''}\n"
            )
    else:
        lines.append("  пусто\n")

    full = "\n".join(lines)
    for part in chunk_text(full):
        await update.message.reply_text(part, parse_mode="HTML")


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/users — список всех пользователей бота."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    users = db.get_all_users(limit=100)
    if not users:
        await update.message.reply_text("Пользователей пока нет.")
        return

    lines = [f"👥 <b>Пользователи ({len(users)}):</b>\n"]
    for u in users:
        name = ((u["first_name"] or "") + " " + (u["last_name"] or "")).strip() or "—"
        uname = f"@{u['username']}" if u["username"] else "—"
        lines.append(f"• <code>{u['user_id']}</code>  {name}  {uname}  {fmt_dt(u['created_at'])}")

    full = "\n".join(lines)
    for part in chunk_text(full):
        await update.message.reply_text(part, parse_mode="HTML")


# ── /myid, /cancel, /help ─────────────────────────────────

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        f"🪪 Твой Telegram ID: <code>{uid}</code>",
        parse_mode="HTML",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (
        "📖 <b>Команды:</b>\n\n"
        "/start — получить свою ссылку\n"
        "/myid — узнать свой Telegram ID\n"
        "/cancel — отменить текущее действие\n"
        "/help — эта справка"
    )
    if is_admin(uid):
        text += (
            "\n\n🔐 <b>Админ:</b>\n"
            "/logs — последние 30 сообщений\n"
            "/logs @username — вся переписка пользователя\n"
            "/logs 123456789 — то же по числовому id\n"
            "/users — список всех пользователей"
        )
    await update.message.reply_text(text, parse_mode="HTML")


# ── Запуск ─────────────────────────────────────────────────

def main():
    db.init_db()
    logger.info("БД инициализирована")

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(reply_callback, pattern=r"^reply:"),
        ],
        states={
            WAITING_ANON_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_anon_message),
            ],
            WAITING_REPLY_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_reply),
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
    app.add_handler(CommandHandler("logs", admin_logs))
    app.add_handler(CommandHandler("users", admin_users))

    logger.info("Бот запущен")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()