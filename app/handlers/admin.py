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
from app.services.challenge import force_cancel_all
from app.services.economy import format_amount
from app.utils.custom_emoji import extract_custom_emoji_ids

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("reset"))
async def reset(message: Message):
    """Force-refunds every open (pending/accepted) challenge bot-wide right
    now, regardless of its 3-min timer. Escape hatch for "something's stuck
    and I want it cleared immediately" -- not something to run routinely,
    since it also cancels any game that's genuinely still in progress and
    about to be picked up normally."""
    if message.from_user.id not in settings.owner_id_set:
        return  # silently ignore -- no error text, so it doesn't hint the command exists

    async with get_session() as session:
        cleared = await force_cancel_all(session)

    if not cleared:
        await message.reply("nothing was open. no challenges to clear.")
        return

    total = sum(c.wager for c in cleared)
    await message.reply(
        f"cleared {len(cleared)} open challenge(s), {format_amount(total)} total refunded."
    )


@router.message(Command("emojiid"))
async def emojiid(message: Message):
    if message.from_user.id not in settings.owner_id_set:
        return  # silently ignore -- no error text, so it doesn't hint the command exists

    ids = extract_custom_emoji_ids(message)
    if not ids:
        await message.reply(
            "no custom emoji found. reply to a message with one, or send it "
            "right after the command (e.g. <code>/emojiid</code> replying to one)."
        )
        return

    lines = ["<b>Custom emoji ID(s)</b>"] + [f"<code>{cid}</code>" for cid in ids]
    await message.reply("\n".join(lines))
