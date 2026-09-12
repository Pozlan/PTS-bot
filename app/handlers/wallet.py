from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, desc

from app.database.db import get_session
from app.database.models import PlayerState, User, Transaction, Gift
from app.services.economy import (
    get_or_create_user, get_or_create_group, get_or_create_state, format_amount,
    available_balance, GLOBAL_ID,
)
from app.services.gifts import badge_tag, player_cabinet
from app.services.premium_emoji import pe, raw_tag
from app.utils.html_esc import esc

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("start"))
async def start(message: Message):
    """Kept short and formal on purpose -- the DM /start (inbox.py) carries
    the full welcome copy, banner, and PTS mark; this one just confirms the
    bot's alive in the group and points at /help."""
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        await get_or_create_state(session, user.id, message.chat.id)
    await message.reply(f"{pe('play')} <b>pts</b> is live in this chat. use <code>/help</code> to see the commands.")


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.reply(
        f"{pe('play')} <b>pts commands</b>\n"
        "\n"
        "<b>Earn</b>\n"
        "<code>/farm</code>: daily claim\n"
        "<code>/work</code>: take a job\n"
        "<code>/loot</code>: chance find\n"
        "<code>/hunt &lt;amount&gt;</code>: risk it for more\n"
        "<code>/luck</code>: daily gamble\n"
        "\n"
        "<b>Play</b>\n"
        "<code>/rps &lt;amount&gt;</code>: rock paper scissors\n"
        "<code>/coin &lt;amount&gt;</code>: coin flip\n"
        "<code>/dice &lt;amount&gt;</code>: dice duel\n"
        "<code>/highlow &lt;amount&gt;</code>: guess the next card, cash out anytime\n"
        "<code>/dart &lt;amount&gt;</code>: throw a dart, payout depends on the throw\n"
        "<code>/cancel</code>: refund your own unaccepted hosted game\n"
        "<i>(blackjack, slots: coming soon)</i>\n"
        "\n"
        "<b>Social</b>\n"
        "<code>/tip &lt;amount&gt;</code>: reply to someone to send them pts\n"
        "<code>/rob</code>: reply to someone to try to rob them\n"
        "<code>/protect</code>: 24h robbery shield\n"
        "\n"
        "<b>Flex</b>\n"
        "<code>/shop</code>: spend pts on collectible gifts\n"
        "<code>/equip</code>: pick a badge to show next to your name\n"
        "\n"
        "<b>You</b>\n"
        "<code>/bal</code>: your balance, global, same everywhere\n"
        "<code>/stats</code>: your record\n"
        "<code>/top</code>: leaderboard for this group\n"
        "<code>/gtop</code>: global leaderboard, every group\n"
        "\n"
        "DM me <code>/bal</code>, <code>/stats</code>, or <code>/gtop</code> any time to check in privately."
    )


@router.message(Command("bal"))
async def bal(message: Message):
    """Balance is global (see economy.GLOBAL_ID) — same number in every
    group. Also surfaces anything currently locked in an open challenge you
    hosted, so a stuck reservation is never invisible again. total_wagered
    lives here now -- moved off /stats, which is pure flex these days."""
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)
        badge = await badge_tag(session, state)

    lines = [f"<b>{esc(user.full_name)}</b>{badge}", format_amount(state.balance)]
    if state.reserved > 0:
        lines.append(f"{pe('afk')} {format_amount(state.reserved)} locked in an open challenge")
        lines.append(f"available: {format_amount(available_balance(state))}")
    lines.append(f"{pe('wager')} {format_amount(state.total_wagered)} total wagered")
    await message.reply("\n".join(lines))


@router.message(Command("top"))
async def top(message: Message):
    """Group-local leaderboard. Balances are global (see economy.GLOBAL_ID),
    so 'local to this group' means: rank by global balance, but only
    include players with actual transaction history in THIS group -- pulled
    from the ledger, which still records the real group_id per action even
    though the wallet itself isn't split per group anymore."""
    async with get_session() as session:
        group_member_ids = select(Transaction.user_id).where(Transaction.group_id == message.chat.id).distinct()
        stmt = (
            select(PlayerState, User, Gift.emoji_id)
            .join(User, User.id == PlayerState.user_id)
            .outerjoin(Gift, Gift.id == PlayerState.equipped_gift_id)
            .where(PlayerState.group_id == GLOBAL_ID, PlayerState.user_id.in_(group_member_ids))
            .order_by(desc(PlayerState.balance))
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()

    if not rows:
        await message.reply(f"{pe('top')} nobody's played in this group yet.")
        return

    lines = [f"{pe('top')} <b>LEADERBOARD</b>", ""]
    for i, (state, player, badge_id) in enumerate(rows, start=1):
        badge = f" {raw_tag(badge_id)}" if badge_id else ""
        lines.append(f"{i}. {esc(player.display_name)}{badge} · {format_amount(state.balance)}")
    lines.append("")
    lines.append("this group only. <code>/gtop</code> for everyone, everywhere.")
    await message.reply("\n".join(lines))


@router.message(Command("gtop"))
async def gtop(message: Message):
    """True global top 10, every player, every group."""
    async with get_session() as session:
        stmt = (
            select(PlayerState, User, Gift.emoji_id)
            .join(User, User.id == PlayerState.user_id)
            .outerjoin(Gift, Gift.id == PlayerState.equipped_gift_id)
            .where(PlayerState.group_id == GLOBAL_ID)
            .order_by(desc(PlayerState.balance))
            .limit(10)
        )
        rows = (await session.execute(stmt)).all()

    if not rows:
        await message.reply(f"{pe('top')} nobody's on the board yet. play something first.")
        return

    lines = [f"{pe('top')} <b>PTS GLOBAL LEADERBOARD</b>", ""]
    for i, (state, player, badge_id) in enumerate(rows, start=1):
        badge = f" {raw_tag(badge_id)}" if badge_id else ""
        lines.append(f"{i}. {esc(player.display_name)}{badge} · {format_amount(state.balance)}")
    await message.reply("\n".join(lines))


@router.message(Command("stats"))
async def stats(message: Message):
    """Pure flex screen now -- no W/L, no win rate, no rank, no wager
    (that's /bal's job). Just your name, your equipped badge, your
    balance, and your gift cabinet from /shop."""
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        state = await get_or_create_state(session, user.id, message.chat.id)
        badge = await badge_tag(session, state)
        cabinet = await player_cabinet(session, user.id)

    lines = [f"<b>{esc(user.full_name)}</b>{badge}", format_amount(state.balance), ""]
    lines.append(f"{pe('vip')} <b>Gift Cabinet</b>")
    if not cabinet:
        lines.append("empty. check /shop and start flexing.")
    else:
        by_category: dict[str, list[Gift]] = {}
        for g in cabinet:
            by_category.setdefault(g.category, []).append(g)
        for category, gifts in by_category.items():
            tags = " ".join(raw_tag(g.emoji_id) for g in gifts)
            lines.append(f"{esc(category)}: {tags}")
        lines.append("")
        worth = sum(g.price for g in cabinet)
        lines.append(f"{raw_tag('5375296873982604963')} <b>Worth:</b> {worth:,}")
    await message.reply("\n".join(lines))
    
