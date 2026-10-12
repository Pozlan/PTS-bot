"""
/rob hit-counter rules, kept free of database code so they are easy to test.

A player who was robbed `max_hits` times is safe until the counter resets.
The counter resets when the player runs /protect, OR by itself once
`reset_s` seconds have passed since their last hit.
"""
from datetime import datetime, timedelta


def refresh_hits(state, now: datetime, reset_s: int) -> int:
    """Resets state.hits_since_protection to 0 if the last hit is old enough
    (or unknown -- old rows from before last_hit_at existed). Returns the
    current hit count."""
    hits = state.hits_since_protection or 0
    if hits <= 0:
        return 0
    last = state.last_hit_at
    if last is None or now - last >= timedelta(seconds=reset_s):
        state.hits_since_protection = 0
        return 0
    return hits


def safe_minutes_left(state, now: datetime, reset_s: int) -> int:
    """Whole minutes (rounded up, at least 1) until the counter resets."""
    if state.last_hit_at is None:
        return 1
    left = (state.last_hit_at + timedelta(seconds=reset_s) - now).total_seconds()
    return max(1, int(-(-left // 60)))
