from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, desc

from app.database.db import get_session
from app.database.models import PlayerState, User
from app.services.economy import (
    get_or_create_user, get_or_create_group, get_or_create_state, format_amount,
    available_balance, GLOBAL_ID,
)
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
        "Welcome to PTS [ 5893321843149902412 ] Your points. Your luck. "
        "Your problem. Use <code>/help</code> to see the commands."
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
        "<code>/bal</code> — your balance (global — same everywhere)\n"
        "<code>/stats</code> — your record\n"
        "<code>/top</code> or <code>/gtop</code> — global leaderboard\n"
        "\n"
        "DM me <code>/bal</code>, <code>/stats</code>, or <code>/gtop</code> any time to check in privately."
    )


@router.message(Command("bal"))
async def bal(message: Message):
    """Balance is global (see economy.GLOBAL_ID) — same number in every
    group. Also surfaces anything currently locked in an open challenge you
    hosted, so a stuck reservation is never invisible again."""
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)

    lines = [f"<b>{esc(user.full_name)}</b>", format_amount(state.balance)]
    if state.reserved > 0:
        lines.append(f"{pe('afk')} {format_amount(state.reserved)} locked in an open challenge")
        lines.append(f"available: {format_amount(available_balance(state))}")
    await message.reply("\n".join(lines))


@router.message(Command("top", "gtop"))
async def top(message: Message):
    """Global top 10 by balance. /top and /gtop are the same list now that
    balances aren't split per group — kept both names since /top already
    existed and /gtop is what was asked for."""
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
        await message.reply(f"{pe('top')} nobody's on the board yet. play something first.")
        return

    lines = [f"{pe('top')} <b>PTS GLOBAL LEADERBOARD</b>", ""]
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
