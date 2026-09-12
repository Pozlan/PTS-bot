"""
/shop service layer (spec: pts sink + pure-flex status system). Every gift
is a single, unique, one-of-one row -- not a "type" with a quantity. Once
bought it's permanently sold; the only way a sold-out gift becomes
available again is the owner adding a brand NEW row via /addgift, never by
un-selling the old one.

Categories are entirely data-driven from what's actually in the `gifts`
table -- no separate config of "which categories exist" to keep in sync.
A category has tiers if ANY of its rows have a non-null tier (Low/Mid/High);
otherwise it's treated as Limited Edition (flat item list, no tier step).
"""
import random
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Gift, PlayerState
from app.services.economy import adjust_balance, available_balance
from app.services.premium_emoji import raw_tag
from app.utils.time import utcnow

TIER_ORDER = {"low": 0, "mid": 1, "high": 2}


class GiftError(ValueError):
    pass


async def get_categories(session: AsyncSession) -> list[dict]:
    """One entry per category: name, whether it has tiers, and a preview
    emoji (a HIGH-tier item for tiered categories -- picked deterministically
    so /shop looks the same each time; a genuinely random item for Limited
    Edition, since there's no 'high tier' to anchor on for those)."""
    all_gifts = list((await session.execute(select(Gift))).scalars())
    by_category: dict[str, list[Gift]] = {}
    for g in all_gifts:
        by_category.setdefault(g.category, []).append(g)

    categories = []
    for name, gifts in by_category.items():
        has_tiers = any(g.tier for g in gifts)
        if has_tiers:
            high = [g for g in gifts if g.tier == "high"]
            preview = min(high, key=lambda g: g.id) if high else min(gifts, key=lambda g: g.id)
        else:
            preview = random.choice(gifts)
        categories.append({"category": name, "has_tiers": has_tiers, "preview_emoji_id": preview.emoji_id})
    categories.sort(key=lambda c: c["category"])
    return categories


async def get_tiers(session: AsyncSession, category: str) -> list[dict]:
    """Low/Mid/High for a tiered category, each with its flat price
    (every item in a tier costs the same) and how many are still available."""
    stmt = select(Gift).where(Gift.category == category)
    gifts = list((await session.execute(stmt)).scalars())
    by_tier: dict[str, list[Gift]] = {}
    for g in gifts:
        by_tier.setdefault(g.tier, []).append(g)

    tiers = []
    for tier, items in by_tier.items():
        available = sum(1 for g in items if g.owner_user_id is None)
        tiers.append({
            "tier": tier,
            "price": items[0].price,
            "available": available,
            "total": len(items),
        })
    tiers.sort(key=lambda t: TIER_ORDER.get(t["tier"], 99))
    return tiers


async def get_items(session: AsyncSession, category: str, tier: str | None) -> list[Gift]:
    """Every item in a category (+tier, if given), sold or not -- the shop
    displays sold ones marked SOLD rather than hiding them."""
    stmt = select(Gift).where(Gift.category == category, Gift.tier == tier).order_by(Gift.id)
    return list((await session.execute(stmt)).scalars())


async def get_gift(session: AsyncSession, gift_id: int) -> Gift | None:
    return await session.get(Gift, gift_id)


async def purchase_gift(session: AsyncSession, state: PlayerState, gift: Gift, group_id: int) -> None:
    """Atomic compare-and-swap: the UPDATE only succeeds if the gift is
    STILL unowned at the moment this runs, closing the race where two
    people tap the same gift within the same instant. Raises GiftError for
    every rejection path (already sold / can't afford) so the handler can
    show the right message without needing to re-check anything itself."""
    if gift.owner_user_id is not None:
        raise GiftError("sold")
    if gift.price > available_balance(state):
        raise GiftError("broke")

    result = await session.execute(
        update(Gift)
        .where(Gift.id == gift.id, Gift.owner_user_id.is_(None))
        .values(owner_user_id=state.user_id, purchased_at=utcnow())
    )
    if result.rowcount == 0:
        raise GiftError("sold")  # someone else bought it a moment before this

    await adjust_balance(session, state, -gift.price, "shop", ref=f"gift#{gift.id}", group_id=group_id)


async def player_cabinet(session: AsyncSession, user_id: int) -> list[Gift]:
    stmt = select(Gift).where(Gift.owner_user_id == user_id).order_by(Gift.category, Gift.id)
    return list((await session.execute(stmt)).scalars())


async def badge_tag(session: AsyncSession, state: PlayerState) -> str:
    """Returns the equipped gift's emoji tag, or '' if nothing's equipped.
    Deliberately tolerant: if the equipped gift somehow no longer exists,
    this returns '' instead of raising, so a badge issue never breaks
    /stats, /bal, /top, or /gtop."""
    if state.equipped_gift_id is None:
        return ""
    gift = await session.get(Gift, state.equipped_gift_id)
    if gift is None:
        return ""
    return " " + raw_tag(gift.emoji_id)
    
