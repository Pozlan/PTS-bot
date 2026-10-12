"""Economy report: ledger classification, percentiles and a small end-to-end run."""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database.models import Base
from app.services.economy import get_or_create_user, get_or_create_group, get_or_create_state, adjust_balance
from app.services.economy_report import (
    classify, percentile, short, build_report, format_report,
    CREATED, REMOVED, TRANSFER, OTHER,
)


def test_classify_faucets_and_sinks():
    assert classify("farm", 100, False) == (CREATED, "farm")
    assert classify("hunt", 100, False)[0] == CREATED
    assert classify("hunt", -100, False)[0] == REMOVED
    assert classify("admin", 100, False)[0] == CREATED
    assert classify("admin", -100, False)[0] == REMOVED
    assert classify("shop", -100, False)[0] == REMOVED   # purchase
    assert classify("shop", 80, False)[0] == CREATED      # old sellback refund


def test_classify_games_house_vs_pvp():
    assert classify("game", 100, True)[0] == CREATED
    assert classify("game", -100, True)[0] == REMOVED
    assert classify("game", 100, False)[0] == TRANSFER
    assert classify("game", -100, False)[0] == TRANSFER


def test_classify_transfers_and_new_kinds():
    assert classify("tip", 5, False)[0] == TRANSFER
    assert classify("rob", -5, False)[0] == TRANSFER
    assert classify("gift_refund", 5, False)[0] == CREATED
    assert classify("market_fee", -5, False)[0] == REMOVED
    assert classify("gift_fee", -5, False)[0] == REMOVED
    assert classify("market_sale", 5, False)[0] == TRANSFER
    assert classify("something_new", 5, False)[0] == OTHER


def test_percentile_matches_sql_percentile_cont():
    assert percentile([], 0.5) == 0
    assert percentile([5], 0.9) == 5
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([10, 20, 30, 40, 50], 0.75) == 40


def test_short_numbers():
    assert short(999) == "999"
    assert short(83_632) == "83.6k"
    assert short(1_455_000_000) == "1.5b"
    assert short(10_000_000) == "10m"
    assert short(-2_500_000) == "-2.5m"


@pytest.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _player(session, uid):
    await get_or_create_user(session, uid, "P", None)
    await get_or_create_group(session, 1, "g")
    return await get_or_create_state(session, uid, 1)


@pytest.mark.asyncio
async def test_report_end_to_end(session_maker):
    async with session_maker() as session:
        a = await _player(session, 1)
        b = await _player(session, 2)
        await adjust_balance(session, a, 10_000, "farm", ref="daily claim", group_id=1)
        await adjust_balance(session, b, 10_000, "farm", ref="daily claim", group_id=1)
        await adjust_balance(session, a, -200, "hunt", ref="failure", group_id=1)
        await adjust_balance(session, a, -300, "shop", ref="gift#1", group_id=1)
        await adjust_balance(session, a, -100, "game", ref="rps#1 house loss", group_id=1)
        await adjust_balance(session, a, 500, "game", ref="coin#2 win", group_id=1)
        await adjust_balance(session, b, -500, "game", ref="coin#2 loss", group_id=1)
        await session.commit()

    async with session_maker() as session:
        r = await build_report(session, 7)

    assert r.players == 2
    assert r.supply == 19_400
    assert sum(r.created.values()) == 20_000
    assert sum(r.removed.values()) == 600
    assert sum(r.transferred.values()) == 500          # counted once, not twice
    assert r.all_created - r.all_removed == r.supply   # transfers net to zero
    assert r.ledger_mismatch_users == 0
    text = format_report(r)
    assert "Supply" in text and "Ledger check: all wallets match" in text


@pytest.mark.asyncio
async def test_report_flags_wallet_not_matching_ledger(session_maker):
    async with session_maker() as session:
        a = await _player(session, 1)
        await adjust_balance(session, a, 1_000, "farm", ref="daily claim", group_id=1)
        a.balance += 777   # a change that skipped the ledger
        await session.commit()
    async with session_maker() as session:
        r = await build_report(session, 7)
    assert r.ledger_mismatch_users == 1
    assert r.ledger_mismatch_total == 777
