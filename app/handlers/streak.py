"""
/streak responses. Two rules hold everywhere in this file:

  1. NO plain digits. Every number a player sees here -- the streak count,
     their best run, the milestone day-count, even the numbers inside the
     cooldown string ("3h 12m") -- goes through the custom d0-d9 glyphs
     via render_number / render_digits. A bare "3" in one of these
     messages means something fell back, not that it was written that way.

  2. NO plain emoji characters in the message source. Every icon is a
     premium <tg-emoji> tag. The plain characters sitting inside those
     tags (🎉, ⏳, the "3" inside a digit glyph) are the fallback content
     Telegram REQUIRES on every custom emoji -- they are never what
     renders for a Premium viewer. If they show up in the chat, the send
     was rejected and safe_reply degraded it; that's a bad-emoji-ID bug
     to chase in the logs, not a missing tag here.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.services import cooldown as cd
from app.database.db import get_session
from app.services.economy import get_or_create_user, get_or_create_group, get_or_create_state
from app.services.premium_emoji import pe, raw_tag, render_digits, render_number
from app.services.streak import activate
from app.utils.html_esc import esc
from app.utils.safe_reply import safe_reply

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("streak"))
async def streak(message: Message):
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)

        result = await activate(session, state)
        streak_best = state.streak_best

    streak_count = result.streak_count

    # Already activated today. This branch used to bail out early with a
    # bare reply that showed no count at all -- yet it's the single most
    # common way /streak gets run, since the cooldown covers a full 24h.
    # It now leads with the ongoing streak in glyphs.
    if not result.activated:
        html_lines = [
            f"{pe('hype')} streak running: {render_number(streak_count)}",
            "",
            f"{pe('afk')} already activated. back in {render_digits(cd.format_remaining(result.remaining))} "
            "or it breaks.",
        ]
        if streak_best > streak_count:
            html_lines.append(f"{pe('ez')} best run: {render_number(streak_best)}")
        await safe_reply(message, "\n".join(html_lines))
        return

    milestone_hit = result.milestone_hit
    milestone_gift = result.milestone_gift
    broken = result.broken

    html_lines = [f"{pe('gg')} streak activated: {render_number(streak_count)}"]

    if broken:
        html_lines += [
            "",
            f"{pe('sad')} you missed the window — streak restarted from {render_number(1)}.",
        ]

    if milestone_hit:
        # The milestone badge's own emoji, straight from the gift row that
        # was just minted for this player (config STREAK_MILESTONES).
        html_lines += [
            "",
            f"{raw_tag(milestone_gift.emoji_id)} <b>{render_number(milestone_hit)}-day milestone!</b>",
            f"{esc(user.full_name)} just earned an exclusive badge. check /stats.",
        ]
    else:
        html_lines.append(f"come back within {render_number(24)}h or it resets.")

    if streak_best > streak_count:
        html_lines += ["", f"{pe('ez')} best run: {render_number(streak_best)}"]

    # No hand-written plain twin: safe_reply derives the degraded version
    # from this text, so the two can't drift out of sync the way they did
    # before (the old plain twin was what produced bare "streak
    # activated: 3" with no glyphs anywhere).
    await safe_reply(message, "\n".join(html_lines))
