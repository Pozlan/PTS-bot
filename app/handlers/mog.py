"""
/mog -- open flex duel, scored off gift-cabinet value (see services/mog.py).
No wager: rides the existing Challenge system purely for its accept/expire
plumbing (wager=0), never touches balance beyond that. Deliberately its
own callback prefix ("mogacc:") instead of the shared "acc:" handler in
pvp_common.py, since that one dispatches by challenge.game and doesn't
know about "mog" -- keeping this isolated means zero risk to the existing
rps/coin/dice accept flow.

/cancel (pvp_common.py) already works on any pending challenge regardless
of game, so a host bailing on an unaccepted /mog challenge is covered for
free. Same for the background expiry sweep in bot.py.
"""
import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.db import get_session
from app.services.challenge import ChallengeError, accept_challenge, create_challenge
from app.services.economy import get_or_create_group, get_or_create_state, get_or_create_user
from app.services.game_common import finalize_pvp
from app.services.mog import score
from app.services.premium_emoji import mog_loser_stamp, mog_winner_stamp, pe
from app.services.response_engine import react
from app.utils.html_esc import esc

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

FLAIR_KEYS = ["mog_flair_1", "mog_flair_2", "mog_flair_3", "mog_flair_4"]
_last_flair: str | None = None


def _random_flair() -> str:
    """Same one-at-a-time / no-immediate-repeat idea as response_engine's
    POOLS, just for the header's custom emoji instead of a text line."""
    global _last_flair
    choices = [k for k in FLAIR_KEYS if k != _last_flair]
    key = random.choice(choices)
    _last_flair = key
    return pe(key)


def _mog_keyboard(challenge_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Accept", callback_data=f"mogacc:{challenge_id}", style="success"),
    ]])


@router.message(Command("mog"))
async def mog_cmd(message: Message):
    user = message.from_user
    async with get_session() as session:
        await get_or_create_user(session, user.id, user.full_name, user.username)
        await get_or_create_group(session, message.chat.id, message.chat.title or "")
        await get_or_create_state(session, user.id, message.chat.id)
        challenge = await create_challenge(session, message.chat.id, "mog", user.id, wager=0)
        challenge_id = challenge.id

    text = (
        f"{pe('mog_logo')} <b>MOG CHECK</b>\n\n"
        f"{esc(user.full_name)} wants to mog someone. who's got the balls?"
    )
    await message.answer(text, reply_markup=_mog_keyboard(challenge_id))


@router.callback_query(F.data.startswith("mogacc:"))
async def on_mog_accept(callback: CallbackQuery):
    challenge_id = int(callback.data.split(":", 1)[1])
    acceptor = callback.from_user

    async with get_session() as session:
        await get_or_create_user(session, acceptor.id, acceptor.full_name, acceptor.username)
        await get_or_create_group(session, callback.message.chat.id, callback.message.chat.title or "")
        try:
            challenge = await accept_challenge(session, challenge_id, acceptor.id)
        except ChallengeError as e:
            await callback.answer(str(e), show_alert=True)
            return

        creator_score = await score(session, challenge.creator_id)
        acceptor_score = await score(session, challenge.acceptor_id)
        if creator_score > acceptor_score:
            winner_id = challenge.creator_id
        elif acceptor_score > creator_score:
            winner_id = challenge.acceptor_id
        else:
            winner_id = None  # draw

        info = await finalize_pvp(session, challenge, winner_id)

    flair = _random_flair()
    header = f"{pe('mog_logo')} <b>MOG RESULTS</b> {flair}"

    if winner_id is None:
        text = f"{header}\n\n{react('mog_draw')}"
    else:
        if winner_id == info["creator_id"]:
            winner_name, loser_name = info["creator_name"], info["acceptor_name"]
        else:
            winner_name, loser_name = info["acceptor_name"], info["creator_name"]
        text = (
            f"{header}\n\n"
            f"{winner_name} is {mog_winner_stamp()}\n\n"
            f"{loser_name} got {mog_loser_stamp()}\n\n"
            f"{react('mog_roast', loser=loser_name)}"
        )

    await callback.message.edit_text(text)
    await callback.answer()
