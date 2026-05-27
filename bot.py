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

WAITING_ANON_MSG    = 1
WAITING_REPLY_TEXT  = 2
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


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def sender_line(msg: dict) -> str:
    parts = []
    if msg.get("sender_name"):
        parts.append(msg["sender_name"])
    if msg.get("sender_username"):
        parts.append(f"@{msg['sender_username']}")
    if msg.get("sender_id"):
        parts.append(f"id: <code>{msg['sender_id']}</code>")
    return " · ".join(parts) if parts else "неизвестен"


def chunk_text(text: str, limit: int = 4000) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text[:limit].rfind("\n")
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:]
    parts.append(text)
    return parts


# ── Доставка сообщений ────────────────────────────────────

def _card_text(msg_id: int, msg_data: dict) -> str:
    return (
        f"💬 <b>У тебя новое анонимное сообщение!</b>\n\n"
        f"{msg_data['text']}\n\n"
        f"<i>⬅️ Свайпни для ответа.</i>"
    )


def _deanon_text(msg_id: int, msg_data: dict) -> str:
    return (
        f"🕵️ <b>Деанон  #{msg_id}</b>\n"
        f"👤 От: {sender_line(msg_data)}\n"
        f"📨 Кому: {msg_data.get('recipient_name', '')} "
        f"(id: <code>{msg_data['recipient_id']}</code>)\n"
        f"🕐 {fmt_dt(msg_data['sent_at'])}"
    )


async def _send_card(bot, chat_id: int, msg_id: int, msg_data: dict, with_deanon: bool):
    recipient_id = msg_data["recipient_id"]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Ответить",
            callback_data=f"reply:{msg_id}:{recipient_id}"
        )]
    ])

    try:
        msg_type = msg_data.get("message_type", "text")
        text = msg_data.get("text", "")

        caption = (
            "💬 <b>У тебя новое анонимное сообщение!</b>\n\n"
            "<i>⬅️ Свайпни для ответа.</i>"
        )

        if msg_type == "text":
            await bot.send_message(
                chat_id,
                f"💬 <b>У тебя новое анонимное сообщение!</b>\n\n{text}\n\n"
                f"<i>⬅️ Свайпни для ответа.</i>",
                parse_mode="HTML",
                reply_markup=keyboard
            )

        elif msg_type == "photo":
            await bot.send_photo(
                chat_id,
                photo=text,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )

        elif msg_type == "video":
            await bot.send_video(
                chat_id,
                video=text,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )

        elif msg_type == "video_note":
            await bot.send_video_note(
                chat_id,
                video_note=text
            )

            await bot.send_message(
                chat_id,
                "💬 <b>Анонимный кружок</b>",
                parse_mode="HTML",
                reply_markup=keyboard
            )

        elif msg_type == "audio":
            await bot.send_audio(
                chat_id,
                audio=text,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )

    except Exception as e:
        logger.warning(f"Карточка → {chat_id}: {e}")
        return

    if with_deanon:
        try:
            await bot.send_message(
                chat_id,
                _deanon_text(msg_id, msg_data),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Деанон → {chat_id}: {e}")


async def deliver_new_message(bot, owner_id: int, msg_id: int, msg_data: dict):
    """
    Рассылка нового сообщения всем получателям:
    - Владелец ссылки: с деаноном если он глобальный админ, иначе без.
    - Совладельцы владельца: всегда без деанона (независимо от статуса владельца).
    - Глобальные админы (если не являются владельцем): всегда с деаноном.
    """
    owner_sees_deanon = is_admin(owner_id)

    # Владелец ссылки
    await _send_card(bot, owner_id, msg_id, msg_data, with_deanon=owner_sees_deanon)

    # Совладельцы — только сообщение, без деанона
    for co in db.get_co_owners(owner_id):
        co_id = co["user_id"]
        # Глобальный админ-совладелец всё равно увидит деанон отдельно ниже
        if not is_admin(co_id):
            await _send_card(bot, co_id, msg_id, msg_data, with_deanon=False)

    # Глобальные админы, которые не являются владельцем и не получили уже
    # already_notified = {owner_id} | {co["user_id"] for co in db.get_co_owners(owner_id)}
    # for admin_id in ADMIN_IDS:
    #     if admin_id not in already_notified:
    #         await _send_card(bot, admin_id, msg_id, msg_data, with_deanon=True)


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
            f"👤 Пишешь анонимно\n\n"
            "✍️ Отправь своё сообщение — получатель не узнает, кто ты.\n\n"
            "<i>Текст, фото, видео, кружки, голосовые. /cancel — отмена.</i>",
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

    co_owners = db.get_co_owners(user.id)
    owned_by  = db.get_owned_by(user.id)

    co_info = ""
    if co_owners:
        names = [c["first_name"] or str(c["user_id"]) for c in co_owners]
        co_info += f"\n👥 Совладельцы: <b>{', '.join(names)}</b>"
    if owned_by:
        owners = [db.get_user_by_id(oid) for oid in owned_by]
        names  = [o["first_name"] or str(o["user_id"]) for o in owners if o]
        co_info += f"\n🔗 Ты совладелец у: <b>{', '.join(names)}</b>"

    await update.message.reply_text(
        f"Начни получать анонимные сообщения прямо сейчас 🚀\n\n"
        f"Твоя ссылка 👇\n"
        f"<code>{link}</code>\n"
        f"Размести эту ссылку ☝️ в описании профиля Telegram/TikTok/Instagram, "
        f"чтобы начать получать анонимные сообщения 💬"
        f"{co_info}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Скопировать ссылку", switch_inline_query=link)],
            [InlineKeyboardButton("👥 Совладельцы", callback_data=f"co:list:{user.id}")],
        ]),
    )
    return ConversationHandler.END


# ── Получение анонимного сообщения ─────────────────────────

async def receive_anon_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    recipient_id = context.user_data.get("recipient_id")

    if not recipient_id:
        await update.message.reply_text("Используй /start чтобы начать.")
        return ConversationHandler.END

    recipient_user = db.get_user_by_id(recipient_id)

    # Тип сообщения
    msg_type = "text"
    content = ""

    if update.message.text:
        msg_type = "text"
        content = update.message.text

    elif update.message.photo:
        msg_type = "photo"
        content = update.message.photo[-1].file_id

    elif update.message.video:
        msg_type = "video"
        content = update.message.video.file_id

    elif update.message.video_note:
        msg_type = "video_note"
        content = update.message.video_note.file_id

    elif update.message.audio:
        msg_type = "audio"
        content = update.message.audio.file_id

    else:
        await update.message.reply_text(
            "❌ Поддерживаются только:\n"
            "• текст\n"
            "• фото\n"
            "• видео\n"
            "• кружки\n"
            "• аудио"
        )
        return WAITING_ANON_MSG

    # Сохраняем
    msg_id = db.save_message(
        recipient_id=recipient_id,
        sender_id=user.id,
        sender_username=user.username or "",
        sender_name=user_display(user),
        text=content,
        message_type=msg_type,
    )

    msg_data = db.get_message(msg_id)

    msg_data["recipient_name"] = (
        ((recipient_user["first_name"] or "") +
         " " +
         (recipient_user["last_name"] or "")).strip()
        if recipient_user else ""
    )

    await deliver_new_message(context.bot, recipient_id, msg_id, msg_data)

    await update.message.reply_text(
        "✅ <b>Сообщение отправлено анонимно!</b>",
        parse_mode="HTML",
    )

    context.user_data.clear()
    return ConversationHandler.END


# ── Ответы на сообщения ────────────────────────────────────

async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, msg_id_str, recipient_id_str = query.data.split(":")
    msg_id = int(msg_id_str)
    recipient_id = int(recipient_id_str)
    user_id = query.from_user.id

    # Может отвечать: владелец, его совладелец, или глобальный админ
    if user_id != recipient_id and not db.is_co_owner(recipient_id, user_id) and not is_admin(user_id):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    msg = db.get_message(msg_id)
    if not msg:
        await query.answer("Сообщение не найдено.", show_alert=True)
        return

    context.user_data["reply_msg_id"]      = msg_id
    context.user_data["reply_sender_id"]   = msg["sender_id"]
    context.user_data["reply_recipient_id"]= recipient_id

    await query.message.reply_text(
        f"↩️ Отвечаешь на сообщение <code>#{msg_id}</code>:\n"
        f"<i>{msg['text'][:200]}</i>\n\n"
        "Напиши свой ответ. /cancel — отмена.",
        parse_mode="HTML",
    )
    return WAITING_REPLY_TEXT


async def receive_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_text = update.message.text
    msg_id    = context.user_data.get("reply_msg_id")
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
            logger.warning(f"Ответ → {sender_id}: {e}")

    await update.message.reply_text("✅ <b>Ответ отправлен!</b>", parse_mode="HTML")
    context.user_data.clear()
    return ConversationHandler.END


# ── Совладельцы (инлайн-меню) ─────────────────────────────

async def co_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    owner_id = int(query.data.split(":")[2])
    if query.from_user.id != owner_id and not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    co_owners = db.get_co_owners(owner_id)
    buttons = []
    if co_owners:
        lines = ["👥 <b>Твои совладельцы:</b>\n"]
        for co in co_owners:
            name  = ((co["first_name"] or "") + " " + (co["last_name"] or "")).strip() or "—"
            uname = f"@{co['username']}" if co["username"] else "—"
            lines.append(f"• {name}  {uname}  <code>{co['user_id']}</code>")
            buttons.append([InlineKeyboardButton(
                f"❌ Удалить {name}",
                callback_data=f"co:remove:{owner_id}:{co['user_id']}"
            )])
        text = "\n".join(lines)
    else:
        text = "👥 <b>Совладельцы:</b>\n\nПока никого нет."

    buttons.append([InlineKeyboardButton("➕ Добавить", callback_data=f"co:add:{owner_id}")])

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


async def co_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    owner_id = int(query.data.split(":")[2])
    if query.from_user.id != owner_id and not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    context.user_data["co_adding_for"] = owner_id
    await query.message.reply_text(
        "➕ <b>Добавление совладельца</b>\n\n"
        "Попроси человека написать /myid — он получит свой числовой ID.\n"
        "Отправь этот ID сюда.\n\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )
    return WAITING_CO_OWNER_ID


async def receive_co_owner_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.user_data.get("co_adding_for")
    if not owner_id:
        return ConversationHandler.END

    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Введи только числовой ID. Попробуй снова или /cancel.")
        return WAITING_CO_OWNER_ID

    co_id = int(text)
    if co_id == owner_id:
        await update.message.reply_text("❌ Нельзя добавить самого себя.")
        return WAITING_CO_OWNER_ID

    co_user = db.get_user_by_id(co_id)
    if not co_user:
        await update.message.reply_text(
            "❌ Пользователь не найден. Убедись, что он уже запустил бота (/start)."
        )
        return WAITING_CO_OWNER_ID

    added = db.add_co_owner(owner_id, co_id)
    name  = co_user["first_name"] or str(co_id)

    if added:
        owner_user  = db.get_user_by_id(owner_id)
        owner_name  = owner_user["first_name"] if owner_user else "кто-то"

        if owner_id in ADMIN_IDS:
            owner_name = '_'
        try:
            await context.bot.send_message(
                co_id,
                f"✅ <b>{owner_name}</b> добавил тебя как совладельца своей ссылки!\n\n"
                "Ты будешь получать все анонимные сообщения в его адрес.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await update.message.reply_text(f"✅ <b>{name}</b> добавлен как совладелец.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"ℹ️ <b>{name}</b> уже является совладельцем.", parse_mode="HTML")

    context.user_data.clear()
    return ConversationHandler.END


async def co_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts    = query.data.split(":")
    owner_id = int(parts[2])
    co_id    = int(parts[3])

    if query.from_user.id != owner_id and not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа.", show_alert=True)
        return

    removed  = db.remove_co_owner(owner_id, co_id)
    co_user  = db.get_user_by_id(co_id)
    name     = co_user["first_name"] if co_user else str(co_id)

    if removed:
        try:
            await context.bot.send_message(co_id, "ℹ️ Тебя удалили из совладельцев анонимной страницы.")
        except Exception:
            pass
        await query.edit_message_text(f"✅ <b>{name}</b> удалён из совладельцев.", parse_mode="HTML")
    else:
        await query.edit_message_text("❌ Не найдено.", parse_mode="HTML")


# ── Админ-команды ─────────────────────────────────────────

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/logs [@username|id] — переписка пользователя или общий лог."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    if not context.args:
        messages = db.get_all_messages(limit=30)
        if not messages:
            await update.message.reply_text("📭 Сообщений пока нет.")
            return
        lines = ["📋 <b>Последние 30 сообщений:</b>\n"]
        for m in messages:
            s = f"@{m['sender_username']}" if m["sender_username"] else m["sender_name"] or "?"
            r = f"@{m['recipient_username']}" if m["recipient_username"] else m["recipient_name"] or "?"
            lines.append(
                f"<code>#{m['id']}</code>{'✅' if m['reply_text'] else ''}  {fmt_dt(m['sent_at'])}\n"
                f"  От: {s} (id <code>{m['sender_id']}</code>)\n"
                f"  Кому: {r} (id <code>{m['recipient_id']}</code>)\n"
                f"  💬 {m['text'][:100]}{'…' if len(m['text'])>100 else ''}\n"
            )
        for part in chunk_text("\n".join(lines)):
            await update.message.reply_text(part, parse_mode="HTML")
        return

    arg = context.args[0]
    target = db.get_user_by_id(int(arg.lstrip("@"))) if arg.lstrip("@").isdigit() else db.get_user_by_username(arg)
    if not target:
        await update.message.reply_text("❌ Пользователь не найден.")
        return

    tid    = target["user_id"]
    tname  = ((target["first_name"] or "") + " " + (target["last_name"] or "")).strip() or str(tid)
    tuname = f"@{target['username']}" if target.get("username") else "—"
    inc    = db.get_messages_for_recipient(tid, limit=30)
    out    = db.get_sent_by_user(tid, limit=30)

    lines = [f"👤 <b>{tname}</b>  {tuname}  id: <code>{tid}</code>\n"]
    lines.append(f"📥 <b>Входящие ({len(inc)}):</b>\n")
    for m in inc:
        lines.append(
            f"  <code>#{m['id']}</code>{'✅' if m['reply_text'] else ''}  {fmt_dt(m['sent_at'])}\n"
            f"  От: {sender_line(m)}\n"
            f"  💬 {m['text'][:120]}{'…' if len(m['text'])>120 else ''}\n"
            + (f"  ↩️ {m['reply_text'][:80]}{'…' if len(m['reply_text'])>80 else ''}\n" if m["reply_text"] else "")
        )
    if not inc:
        lines.append("  пусто\n")

    lines.append(f"\n📤 <b>Исходящие ({len(out)}):</b>\n")
    for m in out:
        r = f"@{m['recipient_username']}" if m["recipient_username"] else m["recipient_name"] or "?"
        lines.append(
            f"  <code>#{m['id']}</code>  {fmt_dt(m['sent_at'])}\n"
            f"  Кому: {r} (id <code>{m['recipient_id']}</code>)\n"
            f"  💬 {m['text'][:120]}{'…' if len(m['text'])>120 else ''}\n"
        )
    if not out:
        lines.append("  пусто\n")

    for part in chunk_text("\n".join(lines)):
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
        name  = ((u["first_name"] or "") + " " + (u["last_name"] or "")).strip() or "—"
        uname = f"@{u['username']}" if u["username"] else "—"
        lines.append(f"• <code>{u['user_id']}</code>  {name}  {uname}  {fmt_dt(u['created_at'])}")
    for part in chunk_text("\n".join(lines)):
        await update.message.reply_text(part, parse_mode="HTML")


async def admin_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/admins — список глобальных админов."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    if not ADMIN_IDS:
        await update.message.reply_text("Список админов пуст (задай ADMIN_IDS в .env).")
        return
    lines = ["🔐 <b>Глобальные администраторы:</b>\n"]
    for aid in ADMIN_IDS:
        u = db.get_user_by_id(aid)
        if u:
            name  = ((u["first_name"] or "") + " " + (u["last_name"] or "")).strip() or "—"
            uname = f"@{u['username']}" if u["username"] else "—"
            lines.append(f"• <code>{aid}</code>  {name}  {uname}")
        else:
            lines.append(f"• <code>{aid}</code>  (ещё не писал боту)")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── /myid, /cancel, /help ─────────────────────────────────

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        f"🪪 Твой Telegram ID: <code>{uid}</code>\n\n"
        "Отправь это число тому, кто хочет добавить тебя совладельцем.",
        parse_mode="HTML",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
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
            "/users — список всех пользователей\n"
            "/admins — список администраторов"
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
            CallbackQueryHandler(co_add_callback, pattern=r"^co:add:"),
        ],
        states={
            WAITING_ANON_MSG: [
                MessageHandler(
                    (
                        filters.TEXT |
                        filters.PHOTO |
                        filters.VIDEO |
                        filters.VIDEO_NOTE |
                        filters.AUDIO
                    ) & ~filters.COMMAND,
                    receive_anon_message
                )
            ],
            WAITING_REPLY_TEXT: [
                MessageHandler(
                    (
                            filters.TEXT |
                            filters.PHOTO |
                            filters.VIDEO |
                            filters.VIDEO_NOTE |
                            filters.AUDIO
                    ) & ~filters.COMMAND,
                    receive_reply
                )
            ],
            WAITING_CO_OWNER_ID: [
                MessageHandler(
                    (
                        filters.TEXT |
                        filters.PHOTO |
                        filters.VIDEO |
                        filters.VIDEO_NOTE |
                        filters.AUDIO
                    ) & ~filters.COMMAND,
                    receive_co_owner_id
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("myid",   myid_cmd))
    app.add_handler(CommandHandler("help",   help_cmd))
    app.add_handler(CommandHandler("logs",   admin_logs))
    app.add_handler(CommandHandler("users",  admin_users))
    app.add_handler(CommandHandler("admins", admin_admins))
    app.add_handler(CallbackQueryHandler(co_list_callback,   pattern=r"^co:list:"))
    app.add_handler(CallbackQueryHandler(co_remove_callback, pattern=r"^co:remove:"))

    logger.info("Бот запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()