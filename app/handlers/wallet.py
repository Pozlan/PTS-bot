from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.services import cooldown as cd
from app.database.db import get_session
from app.services.economy import get_or_create_user, get_or_create_group, get_or_create_state
from app.services.premium_emoji import pe, raw_tag, render_number
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

    # Every branch below spells the count out in the custom d0-d9 digit
    # glyphs (render_number) rather than plain text -- including the
    # already-activated one, which previously bailed out early with a
    # bare reply and was the only /streak response with no glyphs and no
    # count in it at all. Coming back mid-cooldown is the single most
    # common way this command gets run, so it's the response that most
    # needed to show the number.
    if not result.activated:
        remaining = cd.format_remaining(result.remaining)
        html_lines = [
            f"{pe('bolt')} current streak: {render_number(streak_count)}",
            "",
            f"{pe('afk')} already activated. come back in {remaining} or the streak breaks.",
        ]
        if streak_best > streak_count:
            html_lines.append(f"{pe('top')} your best run: {render_number(streak_best)}")
        # safe_reply, not message.reply -- this branch now carries digit
        # tags, so it can be rejected like any other custom-emoji send.
        await safe_reply(message, "\n".join(html_lines))
        return

    milestone_hit = result.milestone_hit
    milestone_gift = result.milestone_gift
    broken = result.broken

    html_lines = [f"{pe('gg')} streak activated: {render_number(streak_count)}"]

    if broken:
        html_lines += ["", f"{pe('sad')} you missed the window — streak restarted from {render_number(1)}."]

    if milestone_hit:
        html_lines += [
            "",
            f"{raw_tag(milestone_gift.emoji_id, '🔥')} <b>{render_number(milestone_hit)}-day milestone!</b>",
            f"{esc(user.full_name)} just earned an exclusive badge. check /stats.",
        ]
    else:
        html_lines.append("come back within 24h or it resets.")

    if streak_best > streak_count:
        html_lines += ["", f"{pe('top')} your best run: {render_number(streak_best)}"]

    # No hand-written plain twin anymore: safe_reply derives the degraded
    # version by stripping each <tg-emoji> down to its own fallback
    # character, so the count survives as normal digits (the d0-d9
    # fallbacks are literally "0"-"9") instead of the message being
    # rebuilt by hand and drifting out of sync with this one.
    await safe_reply(message, "\n".join(html_lines))
