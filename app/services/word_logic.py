"""Pure helpers for /word -- no database, no Telegram, easy to test."""
import re
from collections import Counter

MAX_GUESSES = 30
GREEN, YELLOW, RED = "🟩", "🟨", "🟥"
_EMOJI = {"g": GREEN, "y": YELLOW, "r": RED}


def score_guess(secret: str, guess: str) -> list[str]:
    """Wordle rules: 'g' right place, 'y' right letter wrong place, 'r' not
    in the word (or all copies of that letter are already used up).
    secret=book, guess=boob -> g g g r (the 2nd b has no copy left)."""
    secret, guess = secret.lower(), guess.lower()
    result = ["r"] * len(guess)
    left: Counter = Counter()
    for i, (s, g) in enumerate(zip(secret, guess)):
        if s == g:
            result[i] = "g"
        else:
            left[s] += 1
    for i, g in enumerate(guess):
        if result[i] == "g":
            continue
        if left[g] > 0:
            result[i] = "y"
            left[g] -= 1
    return result


def render_marks(marks: list[str]) -> str:
    return "".join(_EMOJI[m] for m in marks)


_DUR_RE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MIN_CONTEST_S = 60
MAX_CONTEST_S = 7 * 86400


def parse_duration(text: str) -> int | None:
    """'30m' -> 1800, '2h' -> 7200, '1d' -> 86400. None if invalid or out of
    range (1 minute to 7 days)."""
    m = _DUR_RE.match((text or "").strip())
    if not m:
        return None
    seconds = int(m.group(1)) * _UNIT[m.group(2).lower()]
    if seconds < MIN_CONTEST_S or seconds > MAX_CONTEST_S:
        return None
    return seconds


def format_left(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{s}s"
