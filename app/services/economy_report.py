"""
Internal economy report, built from the append-only ledger (Transaction),
the wallets (PlayerState) and the gift tables. Read-only: it never changes
balances. Goal: see whether PTS is being created faster than it is removed.

Buckets
  created      new PTS enters the game (rewards, house-game wins, admin grants...)
  removed      PTS leaves the game (purchases, burned fees, house-game losses...)
  transferred  PTS moves between players (tips, robbery, pvp games, market)
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Gift, GiftEvent, GiftListing, PlayerState, Transaction
from app.services.economy import GLOBAL_ID
from app.services import gift_rules as rules
from app.utils.time import utcnow

CREATED, REMOVED, TRANSFER, OTHER = "created", "removed", "transferred", "other"


def classify(kind: str, amount: int, is_house: bool) -> tuple[str, str]:
    """(bucket, label) for one group of ledger rows. `is_house` is True for
    games played against the bot (their ref text says house / highlow /
    lebron / dart bonus); the other game rows are player-vs-player."""
    if kind in ("farm", "work", "loot", "luck"):
        return CREATED, kind
    if kind == "hunt":
        return (CREATED if amount > 0 else REMOVED), "hunt"
    if kind == "admin":
        return (CREATED, "admin grants") if amount > 0 else (REMOVED, "admin deductions")
    if kind == "shop":
        return (REMOVED, "shop purchases") if amount < 0 else (CREATED, "shop sellbacks")
    if kind == "game":
        if is_house:
            return (CREATED if amount > 0 else REMOVED), "house games"
        return TRANSFER, "pvp games"
    if kind in ("tip", "rob"):
        return TRANSFER, kind
    if kind == rules.KIND_LEGACY_REFUND:
        return CREATED, "old gift refund"
    if kind == rules.KIND_DROP_BUY:
        return REMOVED, "drop purchases"
    if kind == rules.KIND_MARKET_FEE:
        return REMOVED, "market fee (burn)"
    if kind == rules.KIND_GIFT_FEE:
        return REMOVED, "gift fee (burn)"
    if kind in (rules.KIND_MARKET_BUY, rules.KIND_MARKET_SALE):
        return TRANSFER, "market"
    return OTHER, kind


def percentile(values: list[int], p: float) -> float:
    """Linear interpolation, same method as SQL percentile_cont."""
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


@dataclass
class Report:
    days: int
    players: int = 0
    supply: int = 0
    median: int = 0
    p75: int = 0
    p90: int = 0
    p99: int = 0
    richest: int = 0
    top10_share: float = 0.0
    # label -> PTS, inside the window
    created: dict = field(default_factory=dict)
    removed: dict = field(default_factory=dict)
    transferred: dict = field(default_factory=dict)
    other: dict = field(default_factory=dict)
    # all-time totals
    all_created: int = 0
    all_removed: int = 0
    # wallet vs ledger check
    ledger_mismatch_users: int = 0
    ledger_mismatch_total: int = 0
    # old shop stock: tier -> (total, sold)
    legacy_stock: dict = field(default_factory=dict)
    # new system, inside the window
    events: dict = field(default_factory=dict)          # kind -> count
    listings: dict = field(default_factory=dict)        # status -> count
    market_volume: int = 0
    market_fees: int = 0
    avg_hours_to_sale: float | None = None
    expired_by_tier: dict = field(default_factory=dict)  # tier -> count


def _sum(d: dict) -> int:
    return sum(d.values())


async def _ledger_groups(session: AsyncSession, since: datetime | None):
    house = case(
        (or_(
            Transaction.ref.like("%house%"),
            Transaction.ref.like("highlow#%"),
            Transaction.ref.like("lebron%"),
            Transaction.ref.like("dart bullseye%"),
        ), 1),
        else_=0,
    ).label("house")
    pos = (Transaction.amount > 0).label("pos")
    stmt = select(Transaction.kind, pos, house, func.sum(Transaction.amount)).group_by(
        Transaction.kind, pos, house
    )
    if since is not None:
        stmt = stmt.where(Transaction.created_at >= since)
    return (await session.execute(stmt)).all()


def _bucket_totals(rows) -> dict:
    out = {CREATED: {}, REMOVED: {}, TRANSFER: {}, OTHER: {}}
    for kind, pos, house, total in rows:
        total = int(total or 0)
        if total == 0:
            continue
        bucket, label = classify(kind, 1 if pos else -1, bool(house))
        # transfers: count only the receiving side so volume is not doubled
        if bucket == TRANSFER and not pos:
            continue
        out[bucket][label] = out[bucket].get(label, 0) + abs(total)
    return out


async def build_report(session: AsyncSession, days: int = 7) -> Report:
    now = utcnow()
    since = now - timedelta(days=days)
    r = Report(days=days)

    # --- wallets ---
    balances = list((await session.execute(
        select(PlayerState.balance).where(PlayerState.group_id == GLOBAL_ID)
    )).scalars())
    r.players = len(balances)
    r.supply = int(sum(balances))
    r.median = int(percentile(balances, 0.5))
    r.p75 = int(percentile(balances, 0.75))
    r.p90 = int(percentile(balances, 0.9))
    r.p99 = int(percentile(balances, 0.99))
    r.richest = max(balances) if balances else 0
    top10 = sum(sorted(balances, reverse=True)[:10])
    r.top10_share = (top10 / r.supply) if r.supply else 0.0

    # --- ledger: window and all-time ---
    win = _bucket_totals(await _ledger_groups(session, since))
    r.created, r.removed = win[CREATED], win[REMOVED]
    r.transferred, r.other = win[TRANSFER], win[OTHER]
    allt = _bucket_totals(await _ledger_groups(session, None))
    r.all_created, r.all_removed = _sum(allt[CREATED]), _sum(allt[REMOVED])

    # --- wallet vs ledger: every balance should equal the sum of its ledger rows ---
    ledger = dict((await session.execute(
        select(Transaction.user_id, func.sum(Transaction.amount)).group_by(Transaction.user_id)
    )).all())
    states = (await session.execute(
        select(PlayerState.user_id, PlayerState.balance).where(PlayerState.group_id == GLOBAL_ID)
    )).all()
    for uid, bal in states:
        diff = int(bal) - int(ledger.get(uid, 0) or 0)
        if diff != 0:
            r.ledger_mismatch_users += 1
            r.ledger_mismatch_total += diff

    # --- old shop stock (streak badges are not shop stock) ---
    rows = (await session.execute(
        select(Gift.tier, func.count(Gift.id), func.count(Gift.owner_user_id))
        .where(Gift.category != "streak")
        .group_by(Gift.tier)
    )).all()
    for tier, total, sold in rows:
        r.legacy_stock[tier or "limited"] = (int(total), int(sold))

    # --- new gift system (all zero until it is switched on) ---
    for kind, n in (await session.execute(
        select(GiftEvent.kind, func.count(GiftEvent.id))
        .where(GiftEvent.created_at >= since).group_by(GiftEvent.kind)
    )).all():
        r.events[kind] = int(n)
    vol, fees = (await session.execute(
        select(func.coalesce(func.sum(GiftEvent.price), 0), func.coalesce(func.sum(GiftEvent.fee), 0))
        .where(GiftEvent.kind == "sale", GiftEvent.created_at >= since)
    )).one()
    r.market_volume, r.market_fees = int(vol), int(fees)

    for status, n in (await session.execute(
        select(GiftListing.status, func.count(GiftListing.id))
        .where(GiftListing.created_at >= since).group_by(GiftListing.status)
    )).all():
        r.listings[status] = int(n)

    sold = (await session.execute(
        select(GiftListing.created_at, GiftListing.closed_at)
        .where(GiftListing.status == "sold", GiftListing.created_at >= since)
    )).all()
    spans = [(c - s).total_seconds() / 3600 for s, c in sold if c is not None]
    r.avg_hours_to_sale = (sum(spans) / len(spans)) if spans else None

    for tier, n in (await session.execute(
        select(Gift.tier, func.count(GiftListing.id))
        .join(GiftListing, GiftListing.gift_id == Gift.id)
        .where(GiftListing.status == "expired", GiftListing.created_at >= since)
        .group_by(Gift.tier)
    )).all():
        r.expired_by_tier[tier or "limited"] = int(n)

    return r


def short(n: float) -> str:
    """1_234_567 -> '1.2m'. Compact numbers keep the report short."""
    n = float(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit, size in (("b", 1e9), ("m", 1e6), ("k", 1e3)):
        if n >= size:
            v = n / size
            return f"{sign}{v:.1f}".rstrip("0").rstrip(".") + unit
    return f"{sign}{int(n)}"


def _top(d: dict, n: int = 4) -> str:
    items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return " · ".join(f"{k} {short(v)}" for k, v in items) or "none"


def format_report(r: Report) -> str:
    created, removed = _sum(r.created), _sum(r.removed)
    lines = [
        f"<b>Economy · last {r.days}d</b>",
        f"Supply <b>{short(r.supply)}</b> · {r.players} players",
        f"Median {short(r.median)} · p90 {short(r.p90)} · p99 {short(r.p99)} · top 10 hold {r.top10_share:.0%}",
        "",
        f"<b>Created</b> +{short(created)}",
        _top(r.created),
        f"<b>Removed</b> −{short(removed)}",
        _top(r.removed),
        f"<b>Net</b> {'+' if created - removed >= 0 else '−'}{short(abs(created - removed))}"
        f" · moved between players {short(_sum(r.transferred))}",
        f"All time: created {short(r.all_created)} · removed {short(r.all_removed)}",
    ]
    if r.other:
        lines.append(f"Unsorted kinds: {_top(r.other)}")

    if r.legacy_stock:
        stock = " · ".join(f"{t} {s}/{n}" for t, (n, s) in sorted(r.legacy_stock.items()))
        lines += ["", f"<b>Shop gifts</b> sold/total: {stock}"]

    if r.events or r.listings:
        done = r.listings.get("sold", 0)
        closed = done + r.listings.get("expired", 0) + r.listings.get("cancelled", 0)
        conv = f"{done / closed:.0%}" if closed else "n/a"
        tts = f"{r.avg_hours_to_sale:.1f}h" if r.avg_hours_to_sale is not None else "n/a"
        lines += [
            "",
            "<b>Market</b>",
            f"Sales {done} · volume {short(r.market_volume)} · fees burned {short(r.market_fees)}",
            f"Conversion {conv} · avg time to sale {tts}",
            f"Listings: " + (" · ".join(f"{k} {v}" for k, v in sorted(r.listings.items())) or "none"),
        ]
        if r.expired_by_tier:
            lines.append("Expired by tier: " + " · ".join(f"{k} {v}" for k, v in sorted(r.expired_by_tier.items())))
        if r.events:
            lines.append("Gift events: " + " · ".join(f"{k} {v}" for k, v in sorted(r.events.items())))

    lines.append("")
    if r.ledger_mismatch_users:
        lines.append(f"⚠️ Ledger check: {r.ledger_mismatch_users} wallets differ (total {short(r.ledger_mismatch_total)})")
    else:
        lines.append("Ledger check: all wallets match")
    return "\n".join(lines)
