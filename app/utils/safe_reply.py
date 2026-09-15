"""
Wraps message.reply() so one bad/unrecognized custom emoji ID doesn't
silently eat the whole reply. Telegram rejects the ENTIRE sendMessage
call if ANY <tg-emoji emoji-id="..."> tag inside it references an ID it
doesn't recognize -- unlike an unmapped EMOJI_IDS key (which pe() already
degrades to a plain fallback char before the text ever reaches Telegram,
see premium_emoji.py), a bad ID only fails at send time, as a
TelegramBadRequest. Without this, that failure is invisible: any DB
writes the handler already made (inside its own `get_session()` block,
committed before the reply) still happened, but the player never sees a
response at all.

Always build both an HTML version (with tags) and a plain-text fallback
(no tags at all) and pass both here -- if the HTML send fails, the player
still gets the plain version instead of silence.
"""
import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger("ptsbot")


async def safe_reply(message: Message, html_text: str, plain_fallback: str) -> None:
    try:
        await message.reply(html_text)
    except TelegramBadRequest:
        logger.exception("reply failed, likely a bad custom emoji ID -- falling back to plain text")
        await message.reply(plain_fallback)
