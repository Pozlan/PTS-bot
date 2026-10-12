"""/rob hit counter resets by itself, and /hunt win cap is 3x."""
from datetime import timedelta
from types import SimpleNamespace

from app.config import ECONOMY
from app.services.robbery import refresh_hits, safe_minutes_left
from app.utils.time import utcnow

RESET = ECONOMY.ROBBERY_HIT_RESET_S


def _state(hits, last_hit_at):
    return SimpleNamespace(hits_since_protection=hits, last_hit_at=last_hit_at)


def test_reset_window_is_one_hour():
    assert RESET == 3600


def test_still_safe_before_one_hour():
    now = utcnow()
    s = _state(2, now - timedelta(minutes=59))
    assert refresh_hits(s, now, RESET) == 2
    assert s.hits_since_protection == 2


def test_hits_reset_after_one_hour():
    now = utcnow()
    s = _state(2, now - timedelta(hours=1))
    assert refresh_hits(s, now, RESET) == 0
    assert s.hits_since_protection == 0


def test_old_stuck_player_without_timestamp_is_reset():
    s = _state(2, None)
    assert refresh_hits(s, utcnow(), RESET) == 0


def test_zero_hits_stays_zero():
    s = _state(0, None)
    assert refresh_hits(s, utcnow(), RESET) == 0


def test_minutes_left():
    now = utcnow()
    s = _state(2, now - timedelta(minutes=50))
    assert safe_minutes_left(s, now, RESET) == 10
    s = _state(2, now - timedelta(minutes=59, seconds=30))
    assert safe_minutes_left(s, now, RESET) == 1


def test_hunt_win_capped_at_3x_and_stake_cap_unchanged():
    assert max(ECONOMY.HUNT_REWARD_MULT) == 3.0
    assert min(ECONOMY.HUNT_REWARD_MULT) == 1.5
    assert ECONOMY.HUNT_MAX_STAKE == 10_000_000
    assert ECONOMY.HUNT_LOSS_MULT == (0.5, 1.0)
    assert ECONOMY.LEBRON_MAX_WAGER == 500_000
