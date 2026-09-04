"""
DM (private chat) support. Every other router in this project filters to
group/supergroup only, so before this file existed the bot did nothing at
all in a private chat -- not even /start replied.

Scope on purpose: DMs are for checking in (/bal, /stats, /gtop), not for
playing. Games, farming, tipping, robbing etc. all stay group-only -- that's
social by design. Anything else typed here gets a short redirect instead of
being silently ignored.
"""
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from sqlalchemy import select, desc

from app.database.db import get_session
from app.database.models import PlayerState, User
from app.services.economy import get_or_create_user, get_or_create_state, format_amount, available_balance, GLOBAL_ID
from app.services.premium_emoji import pe
from app.utils.html_esc import esc

router = Router()
router.message.filter(F.chat.type == "private")

BANNER_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "pts_banner.png"


@router.message(Command("start"))
async def start_dm(message: Message):
    user = message.from_user
    async with get_session() as session:
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_state(session, user.id)

    caption = (
        f"Welcome to PTS{pe('logo')}\n\n"
        "Play games, challenge your friends and earn PTS\n\n"
        "Think you've got what it takes huh?\n"
        "/help to see the games."
    )
    if BANNER_PATH.exists():
        await message.answer_photo(FSInputFile(BANNER_PATH), caption=caption)
    else:
        await message.reply(caption)


@router.message(Command("bal"))
async def bal_dm(message: Message):
    user = message.from_user
    async with get_session() as session:
        await get_or_create_user(session, user.id, user.full_name, user.username)
        state = await get_or_create_state(session, user.id)

    lines = [f"<b>{esc(user.full_name)}</b>", format_amount(state.balance)]
    if state.reserved > 0:
        lines.append(f"{pe('afk')} {format_amount(state.reserved)} locked in an open challenge")
        lines.append(f"available: {format_amount(available_balance(state))}")
    await message.reply("\n".join(lines))


@router.message(Command("stats"))
async def stats_dm(message: Message):
    user = message.from_user
    async with get_session() as session:
        await get_or_create_user(session, user.id, user.full_name, user.username)
        state = await get_or_create_state(session, user.id)

        rank_stmt = (
            select(PlayerState.user_id)
            .where(PlayerState.group_id == GLOBAL_ID)
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


@router.message(Command("gtop"))
async def gtop_dm(message: Message):
    async with get_session() as session:
        stmt = (
            select(PlayerState, User)
            .join(User, User.id == PlayerState.user_id)
            .where(PlayerState.group_id == GLOBAL_ID)
            .order_by(desc(PlayerState.balance))
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()

    if not rows:
        await message.reply(f"{pe('top')} nobody's on the board yet.")
        return

    lines = [f"{pe('top')} <b>PTS GLOBAL LEADERBOARD</b>", ""]
    for i, (state, player) in enumerate(rows, start=1):
        lines.append(f"{i}. {esc(player.display_name)} · {format_amount(state.balance)}")
    await message.reply("\n".join(lines))


@router.message(Command("top"))
async def top_dm(message: Message):
    """/top is group-local (see handlers/wallet.py::top), which means
    nothing in DM. Redirect to /gtop instead of silently no-op'ing."""
    await message.reply(f"{pe('top')} <code>/top</code> is per-group, use <code>/gtop</code> here instead.")


@router.message(Command("help"))
async def help_dm(message: Message):
    await message.reply(
        f"{pe('play')} in DM you can check <code>/bal</code>, <code>/stats</code>, "
        "and <code>/gtop</code>, that's it here.\nadd me to a group chat to actually play."
    )


@router.message()
async def fallback_dm(message: Message):
    """Anything else typed in DM -- another command, or just a message.
    Catches games/farm/tip/rob/etc. attempts specifically since those only
    exist as group-only routers and would otherwise be silently ignored."""
    await message.reply(
        f"{pe('afk')} that one's group-only, add me to a group chat to play.\n"
        "in here you can check <code>/bal</code>, <code>/stats</code>, and <code>/gtop</code>."
    )
