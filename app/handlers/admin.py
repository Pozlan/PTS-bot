"""
Owner-only tools. Restricted to OWNER_IDS in .env (see app/config.py) --
these bypass all normal economy rules on purpose, so they should never be
reachable by a regular player. Every use is still logged to the
Transaction ledger like any other balance change, so it's auditable.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.database.db import get_session
from app.services.economy import (
    get_or_create_user, get_or_create_group, get_or_create_state,
    parse_amount, InvalidAmount, adjust_balance, format_amount,
)
from app.utils.targeting import resolve_reply_target
from app.utils.html_esc import esc
from app.utils.custom_emoji import extract_custom_emoji_ids
from app.services.premium_emoji import pe

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("grant"))
async def grant(message: Message):
    if message.from_user.id not in settings.owner_id_set:
        return  # silently ignore -- no error text, so it doesn't hint the command exists

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("usage: /grant &lt;amount&gt;  (reply to someone to grant them instead of yourself)")
        return
    try:
        amount = parse_amount(parts[1])
    except InvalidAmount as e:
        await message.reply(f"can't do that: {e}")
        return

    target = resolve_reply_target(message)
    recipient = target if target else message.from_user

    async with get_session() as session:
        await get_or_create_user(session, recipient.id, recipient.full_name, recipient.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, recipient.id, message.chat.id)
        await adjust_balance(session, state, amount, "admin", ref=f"granted by {message.from_user.id}")
        new_balance = state.balance

    await message.reply(f"{pe('cr8')} <b>Grant issued</b>\n{esc(recipient.full_name)} +{format_amount(amount)}\nnew balance: {format_amount(new_balance)}")


@router.message(Command("emojiid"))
async def emojiid(message: Message):
    if message.from_user.id not in settings.owner_id_set:
        return  # silently ignore, same as /grant

    ids = extract_custom_emoji_ids(message)
    if not ids:
        await message.reply(
            "no custom emoji found. reply to a message with one, or send it "
            "right after the command (e.g. <code>/emojiid</code> replying to one)."
        )
        return

    lines = ["<b>Custom emoji ID(s)</b>"] + [f"<code>{cid}</code>" for cid in ids]
    await message.reply("\n".join(lines))
