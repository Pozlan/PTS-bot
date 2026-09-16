"""
/lebron <amount> -- solo vs-house, one throw, same shape as /dart but
using Telegram's basketball dice instead of the dart one.

Telegram's 🏀 dice gives values 1-5 (undocumented but stable behavior,
same caveat as /dart's dartboard values): 1-3 misses the basket, 4-5
makes it. No distinction between a "bank shot" (4) and a "swish" (5) in
the payout -- any make pays the same, per what was actually asked for.

UNLIKE every other game in this codebase, this one is NOT tuned to
EV=0. Miss (3/5) loses the wager, make (2/5) triples it (wager back +
2x profit) -- that's +20% expected value in the PLAYER's favor:
  EV = (3*(-1) + 2*(+2)) / 5 = 1/5 = +0.2
This is a deliberate, known house-losing game, not an accidental repeat
of the old /hunt bug or the pre-rewrite /dart color-guess bug. Capped
at LEBRON_MAX_WAGER (500k, well under DART_MAX_WAGER's 5M) specifically
because of that math -- don't raise the cap without revisiting the odds.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.config import ECONOMY
from app.database.db import get_session
from app.services.economy import (
    get_or_create_user, get_or_create_group, get_or_create_state,
    parse_amount, InvalidAmount, available_balance, format_amount, adjust_balance,
)
from app.services.game_common import finalize_house
from app.services.response_engine import react
from app.services.premium_emoji import pe
from app.utils.html_esc import esc

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("lebron"))
async def lebron_cmd(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("usage: /lebron &lt;amount&gt;  e.g. /lebron 100k")
        return
    try:
        wager = parse_amount(parts[1])
    except InvalidAmount as e:
        await message.reply(f"can't do that: {e}")
        return

    if wager > ECONOMY.LEBRON_MAX_WAGER:
        await message.reply(f"max lebron wager is {format_amount(ECONOMY.LEBRON_MAX_WAGER)}.")
        return

    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)
        if wager > available_balance(state):
            await message.reply("you don't have that much available.")
            return

    throw_msg = await message.answer_dice(emoji="🏀")
    value = throw_msg.dice.value

    lines = [f"{pe('dart')} <b>Lebron · {esc(user.full_name)}</b>", ""]

    async with get_session() as session:
        state = await get_or_create_state(session, user.id, message.chat.id)

        if value >= 4:
            lines.append("smashed it.")
            lines.append(f"{pe('top')} <b>YOU WIN</b>")
            lines.append(f"+{format_amount(wager * 2)}")
            lines.append(react("house_win"))
            # finalize_house only moves the wager 1x on a win, so the extra
            # 1x needed to reach a full 2x-profit (triple total) payout is
            # applied as a separate adjustment, same pattern as dart's
            # bullseye bonus.
            await finalize_house(session, "lebron", state, message.chat.id, wager, True)
            await adjust_balance(session, state, wager, "game", ref="lebron make bonus", group_id=message.chat.id)
        else:
            lines.append("air ball.")
            lines.append(f"{pe('skull')} <b>YOU LOSE</b>")
            lines.append(f"-{format_amount(wager)}")
            lines.append(react("house_loss"))
            await finalize_house(session, "lebron", state, message.chat.id, wager, False)

    await message.answer("\n".join(lines))
