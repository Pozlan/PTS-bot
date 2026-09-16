"""
/mog scores a player's whole gift cabinet, mixing shop-bought tiers with
reclassified streak badges -- both paths, and the value math itself, are
easy to get subtly wrong, so this is tested directly rather than trusted
from a read-through.
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import ECONOMY
from app.database.models import Base, Gift
from app.services.economy import get_or_create_user, get_or_create_group, get_or_create_state
from app.services.mog import classify_gift, score, UNIT_VALUE


@pytest.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _make_player(session, uid, group_id=1):
    await get_or_create_user(session, uid, "P", None)
    await get_or_create_group(session, group_id, "g")
    return await get_or_create_state(session, uid, group_id)


def _gift(**kw) -> Gift:
    defaults = dict(category="hats", tier=None, emoji_id="1", price=0)
    defaults.update(kw)
    return Gift(**defaults)


@pytest.mark.asyncio
async def test_shop_tiers_classify_directly(session_maker):
    async with session_maker() as session:
        assert classify_gift(_gift(tier="low")) == "low"
        assert classify_gift(_gift(tier="mid")) == "mid"
        assert classify_gift(_gift(tier="high")) == "high"


@pytest.mark.asyncio
async def test_untiered_non_streak_category_is_limited_edition(session_maker):
    async with session_maker() as session:
        assert classify_gift(_gift(category="watches", tier=None)) == "limited"


@pytest.mark.asyncio
async def test_streak_badges_reclassified_by_milestone_day_count(session_maker):
    for days, emoji_id in ECONOMY.STREAK_MILESTONES.items():
        gift = _gift(category="streak", tier=None, emoji_id=emoji_id)
        tier = classify_gift(gift)
        if days < 10:
            assert tier == "low", days
        elif days < 50:
            assert tier == "mid", days
        else:
            assert tier == "high", days


@pytest.mark.asyncio
async def test_conversion_ratios_match_spec():
    # 1 limited = 3 high, 1 high = 4 mid, 1 mid = 5 low
    assert UNIT_VALUE["mid"] == 5 * UNIT_VALUE["low"]
    assert UNIT_VALUE["high"] == 4 * UNIT_VALUE["mid"]
    assert UNIT_VALUE["limited"] == 3 * UNIT_VALUE["high"]


@pytest.mark.asyncio
async def test_score_sums_whole_cabinet(session_maker):
    async with session_maker() as session:
        await _make_player(session, 1)
        session.add_all([
            _gift(category="hats", tier="low", emoji_id="a", owner_user_id=1),
            _gift(category="hats", tier="mid", emoji_id="b", owner_user_id=1),
            _gift(category="watches", tier=None, emoji_id="c", owner_user_id=1),  # limited
            _gift(category="streak", tier=None, emoji_id=ECONOMY.STREAK_MILESTONES[50], owner_user_id=1),  # high
            _gift(category="hats", tier="low", emoji_id="d", owner_user_id=2),  # someone else's, not counted
        ])
        await session.commit()

        total = await score(session, 1)
        assert total == UNIT_VALUE["low"] + UNIT_VALUE["mid"] + UNIT_VALUE["limited"] + UNIT_VALUE["high"]
        assert total == 1 + 5 + 60 + 20


@pytest.mark.asyncio
async def test_score_ignores_unowned_gifts(session_maker):
    async with session_maker() as session:
        await _make_player(session, 1)
        session.add(_gift(category="hats", tier="high", emoji_id="unsold", owner_user_id=None))
        await session.commit()

        assert await score(session, 1) == 0
