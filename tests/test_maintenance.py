"""One-time migration tools: ledger correction and old-gift payout."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import ECONOMY
from app.database.models import Base, Gift, LegacyGift, PlayerState, Transaction, User
from app.services.economy import get_or_create_user, get_or_create_group, get_or_create_state, adjust_balance
from app.services.economy_report import build_report
from app.services.maintenance import (
    MaintenanceError, make_token, legacy_warnings,
    plan_ledger_fix, apply_ledger_fix, plan_legacy_payout, run_legacy_payout,
)

M = 1_000_000


def test_token_changes_when_numbers_change():
    assert make_token("gp", 3, 1, 95) == make_token("gp", 3, 1, 95)
    assert make_token("gp", 3, 1, 95) != make_token("gp", 3, 1, 96)


def test_warnings_flag_odd_rows_without_changing_them():
    g = lambda **kw: SimpleNamespace(**{"category": "A", "tier": "low", "emoji_id": "1", "owner_user_id": None, "price": 5, **kw})
    odd = [
        g(tier="weird"), g(emoji_id="abc"), g(emoji_id="1"), g(emoji_id="1"),
        g(category="B", tier=None), g(category="B", tier="low"),
        g(owner_user_id=7, price=0),
    ]
    text = " | ".join(legacy_warnings(odd))
    assert "unknown tier" in text
    assert "non-numeric emoji" in text
    assert "more than one gift" in text
    assert "mix tiered" in text
    assert "price 0" in text
    assert legacy_warnings([g()]) == []


@pytest.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _player(session, uid, extra=0):
    """New wallet. get_or_create_state logs the starting balance in the
    ledger, so wallet and ledger match; `extra` adds a normal farm reward."""
    await get_or_create_user(session, uid, "P", None)
    await get_or_create_group(session, 1, "g")
    st = await get_or_create_state(session, uid, 1)
    if extra:
        await adjust_balance(session, st, extra, "farm", ref="seed", group_id=1)
    return st


async def _seed_gifts(session):
    a = Gift(category="Rolex", tier="low", emoji_id="111", price=5 * M, owner_user_id=1)
    b = Gift(category="Snoop Cars", tier="high", emoji_id="222", price=65 * M, owner_user_id=1)
    c = Gift(category="Snoop Cars", tier="low", emoji_id="333", price=25 * M, owner_user_id=2)
    stock = Gift(category="Jester", tier="low", emoji_id="444", price=5 * M)
    badge = Gift(category="streak", tier=None, emoji_id="555", price=0, owner_user_id=1, soulbound=True)
    new_item = Gift(category="NewDrop", tier="low", emoji_id="666", price=10 * M, owner_user_id=2, release_id=9)
    session.add_all([a, b, c, stock, badge, new_item])
    await session.flush()
    return a, b, c, stock, badge, new_item


@pytest.mark.asyncio
async def test_plan_payout_counts_only_old_shop_gifts(session_maker):
    async with session_maker() as session:
        await _player(session, 1)
        await _player(session, 2)
        await _seed_gifts(session)
        await session.commit()
    async with session_maker() as session:
        plan = await plan_legacy_payout(session)
    assert plan.n_owned == 3 and plan.n_stock == 1
    assert plan.total_worth == 95 * M
    assert plan.refunds == {1: 35 * M, 2: 12_500_000}
    assert plan.total_refund == 47_500_000


@pytest.mark.asyncio
async def test_payout_pays_half_archives_and_keeps_badges(session_maker):
    async with session_maker() as session:
        s1 = await _player(session, 1)
        await _player(session, 2)
        a, b, c, stock, badge, new_item = await _seed_gifts(session)
        s1.equipped_gift_id = b.id
        await session.commit()
        ids = (a.id, b.id, c.id, stock.id, badge.id, new_item.id)
    async with session_maker() as session:
        before = {s.user_id: s.balance for s in (await session.execute(select(PlayerState))).scalars()}
        plan = await plan_legacy_payout(session)
        await run_legacy_payout(session, plan.token)
        await session.commit()

    async with session_maker() as session:
        after = {s.user_id: s for s in (await session.execute(select(PlayerState))).scalars()}
        assert after[1].balance == before[1] + 35 * M
        assert after[2].balance == before[2] + 12_500_000
        assert after[1].equipped_gift_id is None
        left = {g.id for g in (await session.execute(select(Gift))).scalars()}
        assert left == {ids[4], ids[5]}                       # streak badge + new-system item stay
        archived = {r.id: r for r in (await session.execute(select(LegacyGift))).scalars()}
        assert set(archived) == {ids[0], ids[1], ids[2], ids[3]}
        assert archived[ids[1]].emoji_id == "222" and archived[ids[1]].was_equipped is True
        assert archived[ids[3]].owner_user_id is None and archived[ids[3]].refund_amount == 0
        refunds = list((await session.execute(select(Transaction).where(Transaction.kind == "gift_refund"))).scalars())
        assert sorted(t.amount for t in refunds) == [12_500_000, 35 * M]
        report = await build_report(session, 7)
        assert report.ledger_mismatch_users == 0
        assert report.created.get("old gift refund") == 47_500_000


@pytest.mark.asyncio
async def test_payout_cannot_run_twice_or_with_stale_token(session_maker):
    async with session_maker() as session:
        await _player(session, 1)
        await _player(session, 2)
        await _seed_gifts(session)
        await session.commit()
    async with session_maker() as session:
        with pytest.raises(MaintenanceError):
            await run_legacy_payout(session, "wrongtok")
    async with session_maker() as session:
        plan = await plan_legacy_payout(session)
        await run_legacy_payout(session, plan.token)
        await session.commit()
    async with session_maker() as session:
        with pytest.raises(MaintenanceError):
            await run_legacy_payout(session, plan.token)       # nothing left, no double pay
        refunds = list((await session.execute(select(Transaction).where(Transaction.kind == "gift_refund"))).scalars())
        assert len(refunds) == 2


@pytest.mark.asyncio
async def test_ledger_fix_records_difference_without_moving_balance(session_maker):
    async with session_maker() as session:
        st = await _player(session, 1, extra=5_000)
        st.balance -= 400                      # a cut done by hand, not in the ledger
        await session.commit()
    start = ECONOMY.STARTING_BALANCE
    async with session_maker() as session:
        plan = await plan_ledger_fix(session)
        assert [r[3] for r in plan.rows] == [-400]
        assert plan.n_start == 0               # new wallets already logged their start
        with pytest.raises(MaintenanceError):
            await apply_ledger_fix(session, "wrongtok")
        await apply_ledger_fix(session, plan.token)
        await session.commit()
    async with session_maker() as session:
        st = (await session.execute(select(PlayerState).where(PlayerState.user_id == 1))).scalar_one()
        assert st.balance == start + 5_000 - 400                     # unchanged
        row = (await session.execute(select(Transaction).where(Transaction.kind == "ledger_fix"))).scalar_one()
        assert row.amount == -400 and row.balance_after == st.balance
        report = await build_report(session, 7)
        assert report.ledger_mismatch_users == 0
        assert report.removed.get("ledger correction") == 400
        with pytest.raises(MaintenanceError):
            await apply_ledger_fix(session, plan.token)             # already done


async def _old_wallet(session, uid, balance, ledger_total):
    """A wallet from before starting balances were logged: no 'start' row."""
    session.add(User(id=uid, display_name="Old"))
    session.add(PlayerState(user_id=uid, group_id=0, balance=balance))
    if ledger_total:
        session.add(Transaction(group_id=0, user_id=uid, kind="farm", amount=ledger_total,
                                balance_after=ledger_total, ref="old"))
    await session.flush()


@pytest.mark.asyncio
async def test_ledger_fix_records_missing_starting_balance(session_maker):
    start = ECONOMY.STARTING_BALANCE
    async with session_maker() as session:
        await _old_wallet(session, 3, balance=start, ledger_total=0)   # never played after joining
        await session.commit()
    async with session_maker() as session:
        plan = await plan_ledger_fix(session)
        assert plan.n_start == 1 and plan.unexplained == 0
        await apply_ledger_fix(session, plan.token)
        await session.commit()
    async with session_maker() as session:
        kinds = [t.kind for t in (await session.execute(select(Transaction))).scalars()]
        assert kinds == ["start"]                                     # no correction row needed
        assert (await build_report(session, 7)).ledger_mismatch_users == 0


@pytest.mark.asyncio
async def test_ledger_fix_splits_start_from_unexplained_gap(session_maker):
    start = ECONOMY.STARTING_BALANCE
    async with session_maker() as session:
        # ledger says 2,000,000 was earned; wallet holds start + 500,000
        await _old_wallet(session, 4, balance=start + 500_000, ledger_total=2_000_000)
        await session.commit()
    async with session_maker() as session:
        plan = await plan_ledger_fix(session)
        assert plan.n_start == 1
        assert plan.unexplained == (start + 500_000 - 2_000_000) - start      # -1,500,000
        await apply_ledger_fix(session, plan.token)
        await session.commit()
    async with session_maker() as session:
        rows = {t.kind: t.amount for t in (await session.execute(select(Transaction).where(Transaction.kind.in_(["start", "ledger_fix"])))).scalars()}
        assert rows == {"start": start, "ledger_fix": -1_500_000}
        report = await build_report(session, 7)
        assert report.ledger_mismatch_users == 0
        assert report.removed.get("ledger correction") == 1_500_000
