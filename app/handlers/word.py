"""
/word -- 4-letter Wordle-style game for the whole chat.

  /word          start a round (anyone). Whole chat shares ONE secret word and
                 30 guesses. Ends when someone solves it or the guesses run out.
  <4 letters>    a plain 4-letter message is a guess while a round is running.
  /giveup        end the round and show the word (after at least 5 guesses).
  /contest 2h    admin only. Solves during the time count for the contest.
                 When time is up the bot posts the final board and pins it.
  /contest stop  admin only. Ends the running contest now.
  /cotop         live contest board (points earned during the contest only).
  /wordtop       all-time board for this chat.

Needs Group Privacy turned OFF in BotFather, otherwise Telegram does not
send the bot plain messages (only commands) in groups.
"""
import asyncio
import logging
import re
from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReactionTypeEmoji

from app.config import settings
from app.database.db import get_session
from app.database.models import WordContest
from app.services.economy import get_or_create_user
from app.services.premium_emoji import raw_tag
from app.services.word_logic import (
    MAX_GUESSES, MIN_GIVEUP_GUESSES, format_left, parse_duration, render_marks, score_guess,
)
from app.services import wordgame as wg
from app.utils.html_esc import esc
from app.utils.time import utcnow

logger = logging.getLogger("ptsbot.word")

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)  # one at a time per chat
GUESS_RE = re.compile(r"^[A-Za-z]{4}$")
MEDALS = [
    raw_tag("5454329671002918189", "🥇"),
    raw_tag("5454277199387464208", "🥈"),
    raw_tag("5454129194814441654", "🥉"),
]

# custom (premium) emoji -- fallback shows for people without Premium
POPPER = raw_tag("5193018401810822951", "🎉")   # when a word is solved
WORD_ICON = raw_tag("5467538555158943525", "🔤")  # new round
TROPHY = raw_tag("5217822164362739968", "🏆")   # contest messages


def _board_text(rows: list[tuple[str, str, int]]) -> str:
    lines = []
    for i, (name, badge, pts) in enumerate(rows):
        rank = MEDALS[i] if i < 3 else f"{i + 1}."
        lines.append(f"{rank} {esc(name)}{badge} - {pts} {'word' if pts == 1 else 'words'}")
    return "\n".join(lines)


async def _is_admin(message: Message) -> bool:
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True  # anonymous group admin
    if message.from_user.id in settings.owner_id_set:
        return True
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ("creator", "administrator")


@router.message(Command("word"))
async def word_cmd(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    async with _locks[message.chat.id]:
        async with get_session() as session:
            rnd = await wg.get_active_round(session, message.chat.id)
            if rnd is not None:
                used = wg.guesses_of(rnd)
                lines = [f"{render_marks(score_guess(rnd.word, g))}  <b>{g.upper()}</b>" for g in used]
                text = f"a round is already running. {len(used)}/{MAX_GUESSES} guesses used."
                if lines:
                    text += "\n\n" + "\n".join(lines)
                await message.reply(text)
                return
            await wg.start_round(session, message.chat.id, message.from_user.id)
            contest = await wg.get_active_contest(session, message.chat.id)
            left = format_left((contest.ends_at - utcnow()).total_seconds()) if contest else None

    text = (
        f"{WORD_ICON} <b>new word round!</b>\n"
        f"guess the 4-letter word. just type it in the chat. {MAX_GUESSES} guesses for the whole group.\n\n"
        "🟩 right letter, right place\n🟨 right letter, wrong place\n🟥 not in the word"
    )
    if left:
        text += f"\n\n{TROPHY} contest running, {left} left. solves now count."
    await message.reply(text)


@router.message(Command("giveup"))
async def giveup_cmd(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    async with _locks[message.chat.id]:
        async with get_session() as session:
            rnd = await wg.get_active_round(session, message.chat.id)
            if rnd is None:
                await message.reply("no round is running. type /word to start one.")
                return
            used = len(wg.guesses_of(rnd))
            if used < MIN_GIVEUP_GUESSES:
                await message.reply(
                    f"you can only give up after {MIN_GIVEUP_GUESSES} guesses. "
                    f"{used} used so far, keep trying!"
                )
                return
            rnd.status = "gaveup"
            word = rnd.word
            badge = await wg.badge_for(session, message.from_user.id)

    await message.reply(
        f"🏳️ {esc(message.from_user.full_name)}{badge} gave up. the word was <b>{word.upper()}</b>.\n\n"
        "no points for this one. type /word to start a new round."
    )


@router.message(F.text.regexp(GUESS_RE))
async def guess_msg(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    async with _locks[message.chat.id]:
        async with get_session() as session:
            rnd = await wg.get_active_round(session, message.chat.id)
            if rnd is None:
                return  # no round running: stay silent, it's just chat
            user = message.from_user
            await get_or_create_user(session, user.id, user.full_name, user.username)
            res = await wg.submit_guess(session, rnd, user.id, message.text)
            badge = await wg.badge_for(session, user.id)

    name = esc(message.from_user.full_name) + badge
    if res.kind == "invalid":
        await message.reply(f"<b>{res.guess.upper()}</b> isn't a real word.")
    elif res.kind == "duplicate":
        await message.reply(f"<b>{res.guess.upper()}</b> was already guessed.")
    else:
        row = f"{render_marks(res.marks)}  <b>{res.guess.upper()}</b>"
        if res.kind == "ok":
            await message.reply(f"{row}\nguess {res.guess_no}/{MAX_GUESSES} by {name}")
        elif res.kind == "solved":
            extra = " (counts for the contest too)" if res.contest_id else ""
            try:  # 🔥 on the winning guess; chats can disable reactions, so never let this break the reply
                await message.react([ReactionTypeEmoji(emoji="🔥")])
            except Exception:
                logger.warning("could not react in %s", message.chat.id)
            await message.reply(
                f"{row}\n{POPPER} {name} solved it in {res.guess_no} "
                f"{'guess' if res.guess_no == 1 else 'guesses'}! +1 point{extra}\n\n"
                "type /word to play again."
            )
        else:  # failed
            await message.reply(
                f"{row}\n💀 all {MAX_GUESSES} guesses are used. the word was <b>{res.word.upper()}</b>.\n\n"
                "type /word to try a new one."
            )


@router.message(Command("contest"))
async def contest_cmd(message: Message, command: CommandObject):
    if message.from_user is None:
        return
    if not await _is_admin(message):
        await message.reply("only admins can start a contest.")
        return
    arg = (command.args or "").strip().lower()

    if arg == "stop":
        async with get_session() as session:
            contest = await wg.get_active_contest(session, message.chat.id)
            cid = contest.id if contest else None
        if cid is None:
            await message.reply("no contest is running.")
            return
        await finalize_contest(message.bot, cid)
        return

    seconds = parse_duration(arg)
    if seconds is None:
        await message.reply(
            "usage: <code>/contest &lt;time&gt;</code>, like <code>/contest 30m</code>, "
            "<code>/contest 2h</code> or <code>/contest 1d</code> (1 minute to 7 days).\n"
            "stop it early with <code>/contest stop</code>."
        )
        return

    async with get_session() as session:
        existing = await wg.get_active_contest(session, message.chat.id)
        if existing is not None:
            left = format_left((existing.ends_at - utcnow()).total_seconds())
            await message.reply(f"a contest is already running, {left} left.")
            return
        await wg.start_contest(session, message.chat.id, message.from_user.id, seconds)

    await message.reply(
        f"{TROPHY} <b>word contest started!</b> it runs for {format_left(seconds)}.\n"
        "type /word to start a round. every word you solve is 1 point.\n"
        "see the live board with /cotop. the winners are announced when time is up."
    )


@router.message(Command("cotop"))
async def cotop_cmd(message: Message):
    async with get_session() as session:
        contest = await wg.get_active_contest(session, message.chat.id)
        if contest is None:
            await message.reply("no contest is running right now.")
            return
        rows = await wg.leaderboard(session, message.chat.id, contest.id)
        left = format_left((contest.ends_at - utcnow()).total_seconds())
    body = _board_text(rows) if rows else "nobody has solved a word yet."
    await message.reply(f"{TROPHY} <b>contest board</b> ({left} left)\n\n{body}")


@router.message(Command("wordtop"))
async def wordtop_cmd(message: Message):
    async with get_session() as session:
        rows = await wg.leaderboard(session, message.chat.id)
    body = _board_text(rows) if rows else "nobody has solved a word here yet. type /word!"
    await message.reply(f"📚 <b>all-time word board</b>\n\n{body}", )


async def finalize_contest(bot: Bot, contest_id: int) -> None:
    """Ends the contest, posts the final board, pins it. Safe to call twice:
    the second call finds it already ended and does nothing."""
    async with get_session() as session:
        contest = await session.get(WordContest, contest_id)
        if contest is None or contest.status != "active":
            return
        contest.status = "ended"
        group_id = contest.group_id
        rows = await wg.leaderboard(session, group_id, contest_id)

    if rows:
        text = f"🏁 <b>word contest is over!</b>\n\n{_board_text(rows)}\n\ncongrats to the winners! 🎉"
    else:
        text = "🏁 <b>word contest is over!</b>\n\nnobody solved a word this time."
    try:
        sent = await bot.send_message(group_id, text)
    except Exception:
        logger.exception("could not send contest results to %s", group_id)
        return
    try:
        await bot.pin_chat_message(group_id, sent.message_id, disable_notification=False)
    except Exception:
        logger.warning("could not pin contest results in %s", group_id)
        try:
            await bot.send_message(group_id, "i couldn't pin the results. give me the 'pin messages' admin right.")
        except Exception:
            pass


async def contest_sweep_loop(bot: Bot) -> None:
    """Checks every 15s for contests whose time is up. Reads the database
    each time, so a restart of the bot never loses a running contest."""
    while True:
        try:
            async with get_session() as session:
                due = await wg.due_contest_ids(session)
            for cid in due:
                await finalize_contest(bot, cid)
        except Exception:
            logger.exception("contest sweep failed")
        await asyncio.sleep(15)
  
