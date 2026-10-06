"""
Keeps the background sweeps from hitting the database when nothing can be due.

Why: the free Neon database goes to sleep when idle. A sweep that queries
every 15 seconds would keep it awake all month. So instead each sweep keeps
the deadlines it knows about in memory (a game's expiry time, a contest's end
time) and only queries the database when one of them has passed. The first
check after a restart always queries once, so nothing is forgotten.
"""
from datetime import datetime

from app.utils.time import utcnow


class Gate:
    def __init__(self) -> None:
        self._due: list[datetime] = []

    def note(self, when: datetime) -> None:
        self._due.append(when)

    def is_due(self) -> bool:
        now = utcnow()
        return any(d <= now for d in self._due)

    def clear_due(self) -> None:
        now = utcnow()
        self._due = [d for d in self._due if d > now]


challenge_gate = Gate()  # game expiry times
contest_gate = Gate()    # contest end times
