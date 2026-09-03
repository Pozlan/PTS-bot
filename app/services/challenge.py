"""
Spec section 13 + 34: one reusable challenge system for RPS/Coin/Dice/HighLow
instead of duplicating accept/expire/validate logic per game.

Security model (section 34) — every one of these is enforced here, not
trusted from Telegram callback data:
  - challenge exists
  - not expired
  - not already accepted/resolved
  - acceptor isn't the creator
  - acceptor has enough available balance
  - wager is reserved (not deducted) until resolution, so a crash between
    accept and resolve never loses or duplicates pts
"""
import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Challenge, PlayerState
from app.services.economy import get_or_create_state, reserve, release_reservation, InsufficientBalance
from app.config import ECONOMY
from app.utils.time import utcnow as _now


class ChallengeError(ValueError):
    pass


async def create_challenge(
    session: AsyncSession, group_id: int, game: str, creator_id: int, wager: int, state: dict | None = None
) -> Challenge:
    creator_state = await get_or_create_state(session, creator_id, group_id)
    await reserve(session, creator_state, wager)  # raises InsufficientBalance if not enough

    challenge = Challenge(
        group_id=group_id,
        game=game,
        creator_id=creator_id,
        wager=wager,
        status="pending",
        expires_at=_now() + timedelta(seconds=ECONOMY.CHALLENGE_EXPIRATION_S),
        state=json.dumps(state or {}),
    )
    session.add(challenge)
    await session.flush()
    return challenge


async def get_challenge(session: AsyncSession, challenge_id: int) -> Challenge | None:
    return await session.get(Challenge, challenge_id)


async def accept_challenge(session: AsyncSession, challenge_id: int, acceptor_id: int) -> Challenge:
    challenge = await session.get(Challenge, challenge_id)
    if challenge is None:
        raise ChallengeError("this challenge no longer exists.")
    if challenge.status != "pending":
        raise ChallengeError("this challenge has already been settled.")
    if challenge.expires_at < _now():
        challenge.status = "expired"
        await _refund_creator(session, challenge)
        raise ChallengeError("this challenge expired.")
    if acceptor_id == challenge.creator_id:
        raise ChallengeError("you can't accept your own challenge.")

    acceptor_state = await get_or_create_state(session, acceptor_id, challenge.group_id)
    try:
        await reserve(session, acceptor_state, challenge.wager)
    except InsufficientBalance:
        raise ChallengeError("not enough pts to accept this.")

    challenge.acceptor_id = acceptor_id
    challenge.status = "accepted"
    await session.flush()
    return challenge


async def resolve_challenge(
    session: AsyncSession, challenge: Challenge, winner_id: int | None
) -> None:
    """winner_id=None means a draw — both reservations released, no transfer."""
    creator_state = await get_or_create_state(session, challenge.creator_id, challenge.group_id)
    acceptor_state = await get_or_create_state(session, challenge.acceptor_id, challenge.group_id)
    pot = challenge.wager * 2

    await release_reservation(session, creator_state, challenge.wager)
    await release_reservation(session, acceptor_state, challenge.wager)

    from app.services.economy import adjust_balance
    if winner_id is None:
        pass  # nothing to transfer, reservations already released = wagers returned
    elif winner_id == challenge.creator_id:
        await adjust_balance(session, creator_state, challenge.wager, "game", ref=f"{challenge.game}#{challenge.id} win", group_id=challenge.group_id)
        await adjust_balance(session, acceptor_state, -challenge.wager, "game", ref=f"{challenge.game}#{challenge.id} loss", group_id=challenge.group_id)
    else:
        await adjust_balance(session, acceptor_state, challenge.wager, "game", ref=f"{challenge.game}#{challenge.id} win", group_id=challenge.group_id)
        await adjust_balance(session, creator_state, -challenge.wager, "game", ref=f"{challenge.game}#{challenge.id} loss", group_id=challenge.group_id)

    challenge.status = "resolved"


async def cancel_expired(session: AsyncSession) -> list[Challenge]:
    """Call periodically (or lazily on access) to refund expired pending challenges."""
    stmt = select(Challenge).where(Challenge.status == "pending", Challenge.expires_at < _now())
    expired = list((await session.execute(stmt)).scalars())
    for challenge in expired:
        await _refund_creator(session, challenge)
        challenge.status = "expired"
    return expired


async def _refund_creator(session: AsyncSession, challenge: Challenge) -> None:
    creator_state = await get_or_create_state(session, challenge.creator_id, challenge.group_id)
    await release_reservation(session, creator_state, challenge.wager)
