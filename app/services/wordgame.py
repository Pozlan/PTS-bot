"""Database side of /word. Functions take the caller's session (same pattern
as services/economy.py) so the handler decides when to commit."""
import random
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, WordContest, WordRound, WordSolve
from app.services.word_logic import MAX_GUESSES, score_guess
from app.services.wordlist import ANSWERS, VALID
from app.utils.time import utcnow


async def get_active_round(session: AsyncSession, group_id: int) -> WordRound | None:
    res = await session.execute(
        select(WordRound)
        .where(WordRound.group_id == group_id, WordRound.status == "active")
        .order_by(desc(WordRound.id))
        .limit(1)
    )
    return res.scalar_one_or_none()


async def start_round(session: AsyncSession, group_id: int, user_id: int) -> WordRound:
    rnd = WordRound(group_id=group_id, word=random.choice(ANSWERS), started_by=user_id, guesses="")
    session.add(rnd)
    await session.flush()
    return rnd


def guesses_of(rnd: WordRound) -> list[str]:
    return rnd.guesses.split() if rnd.guesses else []


async def get_active_contest(session: AsyncSession, group_id: int) -> WordContest | None:
    """Contest that is still running RIGHT NOW (ends_at in the future)."""
    res = await session.execute(
        select(WordContest)
        .where(
            WordContest.group_id == group_id,
            WordContest.status == "active",
            WordContest.ends_at > utcnow(),
        )
        .order_by(desc(WordContest.id))
        .limit(1)
    )
    return res.scalar_one_or_none()


async def start_contest(session: AsyncSession, group_id: int, user_id: int, seconds: int) -> WordContest:
    contest = WordContest(
        group_id=group_id, started_by=user_id, ends_at=utcnow() + timedelta(seconds=seconds)
    )
    session.add(contest)
    await session.flush()
    return contest


@dataclass
class GuessResult:
    kind: str  # invalid | duplicate | ok | solved | failed
    guess: str = ""
    marks: list[str] | None = None
    guess_no: int = 0
    word: str = ""
    contest_id: int | None = None


async def submit_guess(session: AsyncSession, rnd: WordRound, user_id: int, raw: str) -> GuessResult:
    guess = raw.lower()
    if guess not in VALID:
        return GuessResult("invalid", guess)
    used = guesses_of(rnd)
    if guess in used:
        return GuessResult("duplicate", guess)

    used.append(guess)
    rnd.guesses = " ".join(used)
    marks = score_guess(rnd.word, guess)
    result = GuessResult("ok", guess, marks, len(used), rnd.word)

    if guess == rnd.word:
        rnd.status = "solved"
        rnd.solver_id = user_id
        contest = await get_active_contest(session, rnd.group_id)
        session.add(WordSolve(
            group_id=rnd.group_id, user_id=user_id, round_id=rnd.id,
            contest_id=contest.id if contest else None,
        ))
        result.kind = "solved"
        result.contest_id = contest.id if contest else None
    elif len(used) >= MAX_GUESSES:
        rnd.status = "failed"
        result.kind = "failed"
    await session.flush()
    return result


async def leaderboard(
    session: AsyncSession, group_id: int, contest_id: int | None = None, limit: int = 10
) -> list[tuple[str, int]]:
    """[(display_name, points)], best first. Ties go to whoever reached the
    score first (earliest last-solve)."""
    q = (
        select(WordSolve.user_id, func.count().label("pts"), func.max(WordSolve.created_at).label("last"))
        .where(WordSolve.group_id == group_id)
    )
    if contest_id is not None:
        q = q.where(WordSolve.contest_id == contest_id)
    q = q.group_by(WordSolve.user_id).order_by(desc("pts"), asc("last")).limit(limit)
    rows = (await session.execute(q)).all()
    out: list[tuple[str, int]] = []
    for user_id, pts, _last in rows:
        user = await session.get(User, user_id)
        out.append((user.display_name if user else str(user_id), int(pts)))
    return out


async def due_contest_ids(session: AsyncSession) -> list[int]:
    res = await session.execute(
        select(WordContest.id).where(WordContest.status == "active", WordContest.ends_at <= utcnow())
    )
    return list(res.scalars())
