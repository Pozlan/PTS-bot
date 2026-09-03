from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Cooldown
from app.utils.time import utcnow as _now


async def check(session: AsyncSession, user_id: int, group_id: int, action: str) -> timedelta | None:
    """Returns remaining time if still on cooldown, else None."""
    stmt = select(Cooldown).where(
        Cooldown.user_id == user_id, Cooldown.group_id == group_id, Cooldown.action == action
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    remaining = row.available_at - _now()
    return remaining if remaining.total_seconds() > 0 else None


async def set_cooldown(session: AsyncSession, user_id: int, group_id: int, action: str, seconds: int) -> None:
    stmt = select(Cooldown).where(
        Cooldown.user_id == user_id, Cooldown.group_id == group_id, Cooldown.action == action
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    available_at = _now() + timedelta(seconds=seconds)
    if row is None:
        session.add(Cooldown(user_id=user_id, group_id=group_id, action=action, available_at=available_at))
    else:
        row.available_at = available_at


def format_remaining(td: timedelta) -> str:
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
