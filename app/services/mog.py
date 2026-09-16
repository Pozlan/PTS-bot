"""
/mog -- flex-only stat duel (no pts change hands, no wager). Scores a
player's ENTIRE gift cabinet -- shop-bought and streak-earned -- by
converting every tier into a common "low tier" unit using the ratios
given: 1 limited = 3 high, 1 high = 4 mid, 1 mid = 5 low. Reduced to one
base unit (low = 1):
    low = 1, mid = 5, high = 20, limited = 60

Streak badges are a special case: every Gift row minted by streak.py has
category="streak" and tier=None (see streak.mint_streak_gift), so there's
no tier field to read directly. They're reclassified by milestone
day-count instead, keyed off which STREAK_MILESTONES emoji_id the row
actually has:
    3-day badge          -> low
    10/15/20/30-day badge -> mid
    50-day and up         -> high
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ECONOMY
from app.database.models import Gift
from app.services.gifts import player_cabinet

UNIT_VALUE = {"low": 1, "mid": 5, "high": 20, "limited": 60}


def _build_streak_tier_map() -> dict[str, str]:
    """emoji_id -> tier bucket, built once from ECONOMY.STREAK_MILESTONES
    (the only place the day-count -> emoji_id mapping lives)."""
    mapping = {}
    for days, emoji_id in ECONOMY.STREAK_MILESTONES.items():
        if days < 10:
            mapping[emoji_id] = "low"
        elif days < 50:
            mapping[emoji_id] = "mid"
        else:
            mapping[emoji_id] = "high"
    return mapping


STREAK_TIER_BY_EMOJI = _build_streak_tier_map()


def classify_gift(gift: Gift) -> str:
    """Returns one of "limited"/"high"/"mid"/"low" for any owned gift row,
    shop-bought or streak-earned. Never raises -- an unrecognized streak
    emoji id (e.g. STREAK_MILESTONES changed after this badge was minted)
    falls back to "low" rather than crashing a result card."""
    if gift.category == "streak":
        return STREAK_TIER_BY_EMOJI.get(gift.emoji_id, "low")
    if gift.tier is None:
        return "limited"  # non-streak category with no tier = Limited Edition
    return gift.tier  # "low" | "mid" | "high"


async def score(session: AsyncSession, user_id: int) -> int:
    """Total mog value for one player's full cabinet."""
    owned = await player_cabinet(session, user_id)
    return sum(UNIT_VALUE[classify_gift(g)] for g in owned)
