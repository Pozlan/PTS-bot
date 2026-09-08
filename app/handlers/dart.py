"""
/dart <amount> <white|red> -- solo vs-house, one throw, no hosting/accepting
needed unlike the PvP games. Uses Telegram's real animated dart emoji
(bot.send_dice-style) so it actually looks like a dart being thrown instead
of the bot just declaring a result.

Telegram's dart value is 1-6: 1 means the dart missed the board entirely,
2-6 are all various hits. There's no color info in the API at all -- the
board's colors are just part of the animation. Splitting those 5 hit-values
evenly into two colors isn't possible (5 doesn't divide by 2), so instead:
the dart's value only decides MISS vs HIT, and color is a separate, truly
50/50 coin flip that only happens on an actual hit. That keeps every
outcome exactly fair instead of accidentally favoring one color.

Outcomes:
  - miss (value == 1, ~1-in-6): refund, no win or loss at all
  - hit + guessed the right color (~5-in-12): win, +wager
  - hit + guessed the wrong color (~5-in-12): lose, -wager
"""
import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.config import ECONOMY
from app.database.db import get_session
from app.services.economy import (
    get_or_create_user, get_or_create_group, get_or_create_state,
    parse_amount, InvalidAmount, available_balance, format_amount,
)
from app.services.game_common import finalize_house
from app.services.response_engine import react
from app.services.premium_emoji import pe
from app.utils.html_esc import esc

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

COLORS = ("white", "red")


@router.message(Command("dart"))
async def dart_cmd(message: Message):
    parts = message.text.split()
    if len(parts) < 3 or parts[2].lower() not in COLORS:
        await message.reply("usage: /dart &lt;amount&gt; &lt;white|red&gt;  e.g. /dart 100k white")
        return
    try:
        wager = parse_amount(parts[1])
    except InvalidAmount as e:
        await message.reply(f"can't do that: {e}")
        return
    guess = parts[2].lower()

    if wager > ECONOMY.DART_MAX_WAGER:
        await message.reply(f"max dart wager is {format_amount(ECONOMY.DART_MAX_WAGER)}.")
        return

    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)
        if wager > available_balance(state):
            await message.reply("you don't have that much available.")
            return

    throw_msg = await message.answer_dice(emoji="🎯")
    value = throw_msg.dice.value
    missed = value == 1

    if missed:
        won = None
        color = None
    else:
        color = random.choice(COLORS)
        won = color == guess

    async with get_session() as session:
        state = await get_or_create_state(session, user.id, message.chat.id)
        await finalize_house(session, "dart", state, message.chat.id, wager, won)

    lines = [f"{pe('play')} <b>Dart · {esc(user.full_name)} called {guess}</b>", ""]
    if missed:
        lines.append(f"{pe('wp')} missed the board entirely. wager returned.")
        lines.append(react("draw"))
    elif won:
        lines.append(f"hit <b>{color}</b>. called it.")
        lines.append(f"{pe('top')} <b>YOU WIN</b>")
        lines.append(f"+{format_amount(wager)}")
        lines.append(react("house_win"))
    else:
        lines.append(f"hit <b>{color}</b>. wrong call.")
        lines.append(f"{pe('skull')} <b>YOU LOSE</b>")
        lines.append(f"-{format_amount(wager)}")
        lines.append(react("house_loss"))

    await message.answer("\n".join(lines))
  
