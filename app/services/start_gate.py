"""
Start gate: nobody can use the bot in a group until they have opened it in
DM once (pressed Start). Why: the bot can only DM people who started it, and
every player should see the welcome message once.

- Group COMMANDS from someone who hasn't started -> a short reply with a green
  "Start the bot" button, and the command is NOT run.
- Group BUTTON presses (Accept, Cancel, ...) -> a popup that opens the bot.
- Plain messages pass through (they are just chat). The word game checks the
  `is_started` flag itself, so a guess from a non-started player gets the prompt
  instead of being ignored.
- Any message in DM counts as started. Bot owners are always allowed.
- If the gate itself ever fails (e.g. database hiccup) it lets the update
  through rather than breaking the whole bot.
"""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import settings
from app.database.db import get_session
from app.database.models import StartedUser

logger = logging.getLogger("ptsbot.startgate")

_started: set[int] = set()               # cache, so most checks never hit the database
_last_prompt: dict[int, float] = {}      # user_id -> when we last showed the prompt
PROMPT_COOLDOWN_S = 30                   # don't spam the same person in the group

PROMPT_TEXT = (
    "👋 start the bot first to play.\n"
    "tap the button, press Start, then come back and try again."
)


async def mark_started(user_id: int) -> None:
    if user_id in _started:
        return
    async with get_session() as session:
        if await session.get(StartedUser, user_id) is None:
            session.add(StartedUser(user_id=user_id))
    _started.add(user_id)


async def has_started(user_id: int) -> bool:
    if user_id in _started or user_id in settings.owner_id_set:
        return True
    async with get_session() as session:
        found = await session.get(StartedUser, user_id) is not None
    if found:
        _started.add(user_id)
    return found


def start_link(bot_username: str) -> str:
    return f"https://t.me/{bot_username}?start=play"


async def send_start_prompt(message: Message) -> None:
    uid = message.from_user.id
    now = time.monotonic()
    if now - _last_prompt.get(uid, -1e9) < PROMPT_COOLDOWN_S:
        return
    _last_prompt[uid] = now
    me = await message.bot.me()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Start the bot", url=start_link(me.username), style="success")
    ]])
    await message.reply(PROMPT_TEXT, reply_markup=kb)


def _is_command_for_us(text: str, bot_username: str) -> bool:
    if not text.startswith("/") or len(text) < 2:
        return False
    first = text.split()[0]
    if "@" in first:  # /word@someotherbot is not ours
        return first.split("@", 1)[1].lower() == bot_username.lower()
    return True


class StartGate(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            if isinstance(event, Message):
                if await self._gate_message(event, data):
                    return None
            elif isinstance(event, CallbackQuery):
                if await self._gate_callback(event, data):
                    return None
        except Exception:
            logger.exception("start gate failed, letting the update through")
        return await handler(event, data)

    async def _gate_message(self, message: Message, data: dict) -> bool:
        """True = block this update."""
        user = message.from_user
        data["is_started"] = True
        if user is None or user.is_bot or message.sender_chat is not None:
            return False  # anonymous admins / channel posts can't press Start
        if message.chat.type == "private":
            await mark_started(user.id)
            return False
        started = await has_started(user.id)
        data["is_started"] = started
        if started:
            return False
        me = await message.bot.me()
        if _is_command_for_us(message.text or "", me.username):
            await send_start_prompt(message)
            return True
        return False

    async def _gate_callback(self, callback: CallbackQuery, data: dict) -> bool:
        user = callback.from_user
        msg = callback.message
        if msg is None or user.is_bot:
            return False
        if msg.chat.type == "private":
            await mark_started(user.id)
            return False
        if await has_started(user.id):
            return False
        me = await callback.bot.me()
        await callback.answer("start the bot first, then try again.", url=start_link(me.username))
        return True
