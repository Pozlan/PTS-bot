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

        if not result.activated:
            # No custom digit/gift tags in this branch (just pe('afk'), an
            # already-established emoji), so a plain reply here is fine.
            remaining = cd.format_remaining(result.remaining)
            await message.reply(f"{pe('afk')} already activated. come back in {remaining} or the streak breaks.")
            return

        milestone_hit = result.milestone_hit
        milestone_gift = result.milestone_gift
        broken = result.broken
        streak_count = result.streak_count

    # HTML version uses the custom digit glyphs (render_number) and, on a
    # milestone, the freshly-minted badge's custom emoji -- both are
    # user-supplied IDs Telegram hasn't necessarily validated, so this
    # whole send can fail. The plain version below has no tags at all and
    # is the guaranteed-to-send fallback (see safe_reply).
    html_lines = [f"{pe('gg')} streak activated: {render_number(streak_count)}"]
    plain_lines = [f"streak activated: {streak_count}"]

    if broken:
        html_lines += ["", f"{pe('sad')} you missed the window — streak restarted from 1."]
        plain_lines += ["", "you missed the window — streak restarted from 1."]

    if milestone_hit:
        html_lines += [
            "",
            f"{raw_tag(milestone_gift.emoji_id)} <b>{milestone_hit}-day milestone!</b>",
            f"{esc(user.full_name)} just earned an exclusive badge. check /stats.",
        ]
        plain_lines += [
            "",
            f"{milestone_hit}-day milestone!",
            f"{user.full_name} just earned an exclusive badge. check /stats.",
        ]
    else:
        html_lines.append("come back within 24h or it resets.")
        plain_lines.append("come back within 24h or it resets.")

    await safe_reply(message, "\n".join(html_lines), "\n".join(plain_lines))
