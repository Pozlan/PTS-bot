from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.services import cooldown as cd
from app.database.db import get_session
from app.services.economy import get_or_create_user, get_or_create_group, get_or_create_state
from app.services.premium_emoji import pe, raw_tag, render_number
from app.services.streak import activate
from app.utils.html_esc import esc

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
            await message.reply(
                f"{pe('afk')} already activated. come back in {cd.format_remaining(result.remaining)} "
                f"or the streak breaks."
            )
            return

        milestone_hit = result.milestone_hit
        milestone_gift = result.milestone_gift
        broken = result.broken

    lines = [f"{pe('gg')} streak activated: {render_number(result.streak_count)}"]
    if broken:
        lines.append("")
        lines.append(f"{pe('sad')} you missed the window — streak restarted from 1.")
    if milestone_hit:
        lines.append("")
        lines.append(f"{raw_tag(milestone_gift.emoji_id)} <b>{milestone_hit}-day milestone!</b>")
        lines.append(f"{esc(user.full_name)} just earned an exclusive badge. check /stats.")
    else:
        lines.append("come back within 24h or it resets.")

    await message.reply("\n".join(lines))
