"""
Fixed rules for the new gift economy: plain numbers and tiny helpers, no
database and no imports from the rest of the app (so they are easy to test).

Approved by the owner:
  - official prices are the same for every category in a tier
  - Limited gifts have a custom price per item
  - Limited /mog score comes from the official price (never a resale price)
  - listing minimum 10m, listings last 24h, sale fee 10% from the seller (burned)
  - direct /gift fee 2m (burned)
  - new drops go live 15 minutes after stock is added

NOT final: TIER_SCORE (provisional, to be tested against the prices).
"""
M = 1_000_000

TIER_PRICE = {"low": 10 * M, "mid": 20 * M, "high": 50 * M}
TIER_SCORE = {"low": 10, "mid": 30, "high": 100}      # provisional
LIMITED_SCORE_PER_M = 1.7                             # approved formula

TIERED_RELEASE = {"low": 12, "mid": 8, "high": 3}     # distinct items per release
LIMITED_RELEASE_SIZE = 3

LISTING_MIN_PRICE = 10 * M
LISTING_HOURS = 24
SALE_FEE_PCT = 10
GIFT_FEE = 2 * M
DROP_DELAY_MIN = 15

# Ledger kinds for the new system. Transaction.kind is String(24), keep short.
KIND_LEGACY_REFUND = "gift_refund"   # half of old Worth paid back (creates PTS)
KIND_DROP_BUY = "drop_buy"           # official shop purchase (removes PTS)
KIND_MARKET_BUY = "market_buy"       # buyer pays the listed price
KIND_MARKET_SALE = "market_sale"     # seller receives the listed price
KIND_MARKET_FEE = "market_fee"       # 10% fee, burned (removes PTS)
KIND_GIFT_FEE = "gift_fee"           # 2m /gift fee, burned (removes PTS)


def limited_score(price: int) -> int:
    """/mog score for a Limited gift, from its OFFICIAL price."""
    return round(price / M * LIMITED_SCORE_PER_M)


def item_score(tier: str | None, price: int) -> int:
    if tier is None:
        return limited_score(price)
    return TIER_SCORE[tier]


def sale_fee(price: int) -> int:
    """Marketplace fee, taken from the seller's proceeds (rounded down)."""
    return price * SALE_FEE_PCT // 100


def seller_proceeds(price: int) -> int:
    return price - sale_fee(price)


def min_cost_low_mid_to_beat(score: int) -> int:
    """Cheapest PTS cost of a Low+Mid collection with a /mog score strictly
    above `score`, buying at official prices. Ignores supply limits, so it is
    a lower bound (the real cost can only be higher)."""
    need = score + 1
    best = None
    for mids in range(0, need // TIER_SCORE["mid"] + 2):
        rest = max(0, need - mids * TIER_SCORE["mid"])
        lows = -(-rest // TIER_SCORE["low"])  # ceil
        cost = mids * TIER_PRICE["mid"] + lows * TIER_PRICE["low"]
        if best is None or cost < best:
            best = cost
    return best
