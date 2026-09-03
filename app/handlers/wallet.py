from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, desc

from app.database.db import get_session
from app.database.models import PlayerState, User
from app.services.economy import get_or_create_user, get_or_create_group, get_or_create_state, format_amount
from app.services.premium_emoji import pe
from app.utils.html_esc import esc

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("start"))
async def start(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.reply("add me to a group chat to play — pts only work there.")
        return
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        await get_or_create_state(session, user.id, message.chat.id)
    await message.reply(
        f"{pe('play')} <b>pts</b> is now live in this group.\n\n"
        "new here? send <code>/help</code> to see everything you can do."
    )


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.reply(
        f"{pe('play')} <b>pts commands</b>\n"
        "\n"
        "<b>Earn</b>\n"
        "<code>/farm</code> — daily claim\n"
        "<code>/work</code> — take a job\n"
        "<code>/loot</code> — chance find\n"
        "<code>/hunt &lt;amount&gt;</code> — risk it for more\n"
        "<code>/luck</code> — daily gamble\n"
        "\n"
        "<b>Play</b>\n"
        "<code>/rps &lt;amount&gt;</code> — rock paper scissors\n"
        "<code>/coin &lt;amount&gt;</code> — coin flip\n"
        "<code>/dice &lt;amount&gt;</code> — dice duel\n"
        "<code>/highlow &lt;amount&gt;</code> — guess the next card, cash out anytime\n"
        "<i>(blackjack, slots — coming soon)</i>\n"
        "\n"
        "<b>Social</b>\n"
        "<code>/tip &lt;amount&gt;</code> — reply to someone to send them pts\n"
        "<code>/rob</code> — reply to someone to try to rob them\n"
        "<code>/protect</code> — 24h robbery shield\n"
        "\n"
        "<b>You</b>\n"
        "<code>/bal</code> — your balance\n"
        "<code>/stats</code> — your record\n"
        "<code>/top</code> — group leaderboard"
    )


@router.message(Command("bal"))
async def bal(message: Message):
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)
    await message.reply(f"<b>{esc(user.full_name)}</b>\n{format_amount(state.balance)}")


@router.message(Command("top"))
async def top(message: Message):
    async with get_session() as session:
        stmt = (
            select(PlayerState, User)
            .join(User, User.id == PlayerState.user_id)
            .where(PlayerState.group_id == message.chat.id)
            .order_by(desc(PlayerState.balance))
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()

    if not rows:
        await message.reply(f"{pe('top')} nobody's on the board yet. play something first.")
        return

    lines = [f"{pe('top')} <b>PTS LEADERBOARD</b>", ""]
    for i, (state, player) in enumerate(rows, start=1):
        lines.append(f"{i}. {esc(player.display_name)} · {format_amount(state.balance)}")
    await message.reply("\n".join(lines))


@router.message(Command("stats"))
async def stats(message: Message):
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)

        rank_stmt = (
            select(PlayerState.user_id)
            .where(PlayerState.group_id == message.chat.id)
            .order_by(desc(PlayerState.balance))
        )
        ranking = [row[0] for row in (await session.execute(rank_stmt)).all()]
        rank = ranking.index(user.id) + 1 if user.id in ranking else "-"

        total = state.wins + state.losses
        win_rate = round(state.wins / total * 100) if total else 0

    lines = [
        f"<b>{esc(user.full_name)}</b>",
        f"{format_amount(state.balance)}",
        f"{pe('crossed_swords')} {state.wins}W / {state.losses}L",
        f"{pe('hit')} {win_rate}% win rate",
        f"{pe('wager')} {format_amount(state.total_wagered)} total wagered",
        f"{pe('vip') if rank == 1 else pe('top')} Rank #{rank}",
    ]
    await message.reply("\n".join(lines))
