"""
One-time owner tools for the gift-economy migration. Both are two-step:
a read-only PREVIEW, then a CONFIRM that must carry the preview's token. If
anything changed in between, the token no longer matches and nothing runs.

1) Ledger correction: some wallets differ from their ledger (for example a
   balance cut done by hand in the database). This adds ONE new ledger row per
   wallet that records the difference. Balances never change; rows are only
   added, never edited or deleted.

2) Old-gift payout: takes every old shop gift (not streak badges), saves it in
   legacy_gifts, and pays each owner half of the saved price. All inside one
   database transaction, so it either fully happens or does not happen.
"""
import hashlib
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Gift, LegacyGift, PlayerState, Transaction
from app.config import ECONOMY
from app.services import gift_rules as rules
from app.services.economy import GLOBAL_ID, adjust_balance, get_or_create_state
from app.utils.time import utcnow


class MaintenanceError(Exception):
    """Raised with a short, player-safe reason (shown to the owner)."""


def make_token(*parts) -> str:
    return hashlib.sha1(":".join(str(p) for p in parts).encode()).hexdigest()[:8]


# ---------------------------------------------------------------- ledger fix

@dataclass
class LedgerFixPlan:
    rows: list = field(default_factory=list)   # (user_id, balance, ledger_sum, diff)
    total: int = 0
    n_start: int = 0            # wallets whose starting balance was never recorded
    start_total: int = 0        # PTS those starting balances add up to
    unexplained: int = 0        # what is left after starting balances (the real gap)
    token: str = ""


async def _wallet_diffs(session: AsyncSession) -> list:
    states = (await session.execute(
        select(PlayerState.user_id, PlayerState.balance).where(PlayerState.group_id == GLOBAL_ID)
    )).all()
    ledger = dict((await session.execute(
        select(Transaction.user_id, func.sum(Transaction.amount)).group_by(Transaction.user_id)
    )).all())
    out = []
    for uid, bal in states:
        led = int(ledger.get(uid, 0) or 0)
        bal = int(bal)
        if bal != led:
            out.append((uid, bal, led, bal - led))
    return out


async def _missing_start(session: AsyncSession, uids) -> set:
    """Wallets with a difference and no 'start' ledger row yet. Old wallets
    were created before starting balances were logged."""
    if not uids:
        return set()
    have = set((await session.execute(
        select(Transaction.user_id).where(Transaction.kind == rules.KIND_START, Transaction.user_id.in_(list(uids)))
    )).scalars())
    return set(uids) - have


async def plan_ledger_fix(session: AsyncSession) -> LedgerFixPlan:
    rows = sorted(await _wallet_diffs(session), key=lambda r: r[3])
    total = sum(r[3] for r in rows)
    missing = await _missing_start(session, [r[0] for r in rows])
    start_total = len(missing) * ECONOMY.STARTING_BALANCE
    return LedgerFixPlan(
        rows=rows, total=total, n_start=len(missing), start_total=start_total,
        unexplained=total - start_total,
        token=make_token("lf", len(rows), total, len(missing)),
    )


async def apply_ledger_fix(session: AsyncSession, token: str) -> LedgerFixPlan:
    # Lock every wallet first, THEN measure, so two clicks at the same time
    # cannot both write the correction.
    await session.execute(
        select(PlayerState).where(PlayerState.group_id == GLOBAL_ID).with_for_update()
    )
    plan = await plan_ledger_fix(session)
    if not plan.rows:
        raise MaintenanceError("nothing to correct, every wallet already matches")
    if plan.token != token:
        raise MaintenanceError("numbers changed since the preview, run the command again")
    label = f"balance correction {utcnow():%Y-%m}"
    missing = await _missing_start(session, [r[0] for r in plan.rows])
    for uid, bal, _led, diff in plan.rows:
        rest = diff
        if uid in missing:
            # the starting balance every old wallet got but the ledger never recorded
            session.add(Transaction(
                group_id=GLOBAL_ID, user_id=uid, kind=rules.KIND_START,
                amount=ECONOMY.STARTING_BALANCE, balance_after=ECONOMY.STARTING_BALANCE,
                ref="starting balance (recorded later)",
            ))
            rest -= ECONOMY.STARTING_BALANCE
        if rest != 0:
            session.add(Transaction(
                group_id=GLOBAL_ID, user_id=uid, kind=rules.KIND_LEDGER_FIX,
                amount=rest, balance_after=bal, ref=label,
            ))
    return plan


# ------------------------------------------------------------- legacy payout

@dataclass
class PayoutPlan:
    n_owned: int = 0
    n_stock: int = 0
    total_worth: int = 0
    total_refund: int = 0
    refunds: dict = field(default_factory=dict)    # user_id -> PTS
    counts: dict = field(default_factory=dict)     # user_id -> number of gifts
    n_equipped: int = 0
    warnings: list = field(default_factory=list)
    token: str = ""


def legacy_warnings(gifts) -> list:
    """Odd rows worth knowing about. Nothing is changed or skipped because of
    them: every row is still archived and paid at its saved price."""
    out = []
    odd_tier = [g for g in gifts if g.tier not in (None, "low", "mid", "high")]
    if odd_tier:
        out.append(f"{len(odd_tier)} gifts with an unknown tier")
    bad_emoji = [g for g in gifts if not str(g.emoji_id).isdigit()]
    if bad_emoji:
        out.append(f"{len(bad_emoji)} gifts with a non-numeric emoji id")
    seen: dict = {}
    for g in gifts:
        seen[g.emoji_id] = seen.get(g.emoji_id, 0) + 1
    dup = sum(1 for n in seen.values() if n > 1)
    if dup:
        out.append(f"{dup} emoji ids are used by more than one gift")
    by_cat: dict = {}
    for g in gifts:
        by_cat.setdefault(g.category, set()).add(g.tier)
    # a category that has tiers must not also have rows with no tier
    mixed = [c for c, tiers in by_cat.items() if None in tiers and len(tiers) > 1]
    if mixed:
        out.append(f"{len(mixed)} categories mix tiered and non-tiered gifts")
    free = [g for g in gifts if g.owner_user_id is not None and g.price <= 0]
    if free:
        out.append(f"{len(free)} owned gifts have price 0 (they pay 0)")
    return out


async def _legacy_gifts(session: AsyncSession) -> list:
    """Old shop gifts only: not streak badges, not soulbound, and nothing
    from the new release system (release_id is empty for old gifts)."""
    rows = list((await session.execute(
        select(Gift).where(Gift.category != "streak", Gift.release_id.is_(None))
    )).scalars())
    return [g for g in rows if not g.soulbound]


async def plan_legacy_payout(session: AsyncSession) -> PayoutPlan:
    gifts = await _legacy_gifts(session)
    owned = [g for g in gifts if g.owner_user_id is not None]
    worth: dict = {}
    counts: dict = {}
    for g in owned:
        worth[g.owner_user_id] = worth.get(g.owner_user_id, 0) + int(g.price)
        counts[g.owner_user_id] = counts.get(g.owner_user_id, 0) + 1
    refunds = {uid: w // 2 for uid, w in worth.items()}
    ids = [g.id for g in gifts]
    n_equipped = 0
    if ids:
        n_equipped = int((await session.execute(
            select(func.count(PlayerState.id)).where(PlayerState.equipped_gift_id.in_(ids))
        )).scalar() or 0)
    plan = PayoutPlan(
        n_owned=len(owned),
        n_stock=len(gifts) - len(owned),
        total_worth=sum(worth.values()),
        total_refund=sum(refunds.values()),
        refunds=refunds,
        counts=counts,
        n_equipped=n_equipped,
        warnings=legacy_warnings(gifts),
    )
    plan.token = make_token("gp", plan.n_owned, plan.n_stock, plan.total_worth)
    return plan


async def run_legacy_payout(session: AsyncSession, token: str) -> PayoutPlan:
    plan = await plan_legacy_payout(session)
    if plan.n_owned + plan.n_stock == 0:
        raise MaintenanceError("no old gifts left, already done")
    if plan.token != token:
        raise MaintenanceError("numbers changed since the preview, run the command again")

    gifts = await _legacy_gifts(session)
    ids = [g.id for g in gifts]
    equipped_ids = set((await session.execute(
        select(PlayerState.equipped_gift_id).where(PlayerState.equipped_gift_id.in_(ids))
    )).scalars())
    snapshot = [
        dict(
            id=g.id, category=g.category, tier=g.tier, emoji_id=g.emoji_id, price=int(g.price),
            owner_user_id=g.owner_user_id, purchased_at=g.purchased_at, added_at=g.added_at,
            was_equipped=g.id in equipped_ids,
            refund_amount=(int(g.price) // 2) if g.owner_user_id is not None else 0,
        )
        for g in gifts
    ]

    # 1) free the equipped slots, then delete. The delete must hit every row:
    #    if a second click raced us and already took them, the count is short
    #    and everything rolls back, so nobody is paid twice.
    await session.execute(
        update(PlayerState).where(PlayerState.equipped_gift_id.in_(ids)).values(equipped_gift_id=None)
    )
    result = await session.execute(delete(Gift).where(Gift.id.in_(ids)))
    if result.rowcount != len(ids):
        raise MaintenanceError("gifts changed while running, nothing was done")

    # 2) archive (keeps ids, emoji ids, owners, prices)
    now = utcnow()
    for row in snapshot:
        session.add(LegacyGift(retired_at=now, **row))

    # 3) pay owners: lock the wallets, then one ledger entry per player
    uids = list(plan.refunds)
    if uids:
        await session.execute(
            select(PlayerState).where(PlayerState.user_id.in_(uids), PlayerState.group_id == GLOBAL_ID).with_for_update()
        )
    for uid, amount in plan.refunds.items():
        if amount <= 0:
            continue
        state = await get_or_create_state(session, uid, GLOBAL_ID)
        await adjust_balance(
            session, state, amount, rules.KIND_LEGACY_REFUND,
            ref=f"old gifts x{plan.counts[uid]} (half of worth)", group_id=GLOBAL_ID,
        )
    return plan
