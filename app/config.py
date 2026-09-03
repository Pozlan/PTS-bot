"""
All tunable economy values live here. Nothing gameplay-related should be
hardcoded inside handlers/games/services — pull it from here so balancing
the game never means hunting through source files.

Per-group overrides (via /gconfig) are stored in GroupSettings and layered
on top of these defaults at read time — see services/economy.py:get_group_config.
"""
from dataclasses import dataclass, field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    database_url: str = "sqlite+aiosqlite:///./ptsbot.db"
    owner_ids: str = ""

    class Config:
        env_file = ".env"

    @property
    def owner_id_set(self) -> set[int]:
        return {int(x) for x in self.owner_ids.split(",") if x.strip()}


settings = Settings()


@dataclass(frozen=True)
class EconomyConfig:
    # /farm
    FARM_MIN: int = 800
    FARM_MAX: int = 3200
    FARM_COOLDOWN_S: int = 24 * 3600

    # /work
    WORK_COOLDOWN_S: int = 3 * 3600
    WORK_JOBS: dict = field(default_factory=lambda: {
        "cleaner": (150, 600),
        "delivery driver": (200, 750),
        "freelancer": (250, 1200),
        "mechanic": (300, 900),
        "developer": (400, 1600),
        "chef": (250, 850),
        "driver": (200, 700),
        "security guard": (200, 650),
        "trader": (100, 2000),
        "construction worker": (300, 950),
    })

    # /loot
    LOOT_COOLDOWN_S: int = 2 * 3600
    LOOT_SUCCESS_RATE: float = 0.55
    LOOT_MIN: int = 100
    LOOT_MAX: int = 1500

    # /hunt
    HUNT_COOLDOWN_S: int = 4 * 3600
    HUNT_SUCCESS_RATE: float = 0.5
    HUNT_MIN_STAKE: int = 200
    HUNT_REWARD_MULT: tuple = (1.5, 4.0)   # win: stake * random in this range
    HUNT_LOSS_MULT: tuple = (0.5, 1.0)     # loss: stake * random in this range, deducted

    # /luck
    LUCK_COOLDOWN_S: int = 24 * 3600
    LUCK_POSITIVE_RATE: float = 0.55
    LUCK_WIN_MIN: int = 500
    LUCK_WIN_MAX: int = 12000
    LUCK_LOSS_MIN: int = 300
    LUCK_LOSS_MAX: int = 5000

    # House wager caps (0 = no cap -- unlimited wager allowed vs house)
    RPS_MAX_HOUSE_WAGER: int = 250_000
    COIN_MAX_HOUSE_WAGER: int = 250_000
    DICE_MAX_HOUSE_WAGER: int = 250_000
    # HighLow (solo one-shot game vs house)
    HIGHLOW_MAX_HOUSE_WAGER: int = 250_000
    HIGHLOW_MAX_ROUNDS: int = 15      # unused now that HighLow is one-shot, kept in case a streak mode returns
    BJ_MAX_HOUSE_WAGER: int = 250_000
    SLOTS_MAX_WAGER: int = 250_000

    # PvP challenges
    CHALLENGE_EXPIRATION_S: int = 3 * 60
    CHALLENGE_SWEEP_INTERVAL_S: int = 30  # how often the background task checks for expired challenges to refund

    # Robbery
    ROBBERY_COOLDOWN_S: int = 6 * 3600
    ROBBERY_SUCCESS_RATE: float = 0.45
    ROBBERY_STEAL_PCT: float = 0.20           # flat -- of target's balance, on success
    ROBBERY_MIN_TARGET_BALANCE: int = 5000
    # No failure penalty -- a failed robbery costs the robber nothing but
    # the cooldown. Steal is currently flat 20% on success (was a random
    # 2-15% range with a 5% self-penalty on failure).

    # Protection
    PROTECTION_DURATION_S: int = 24 * 3600
    DOOR_DURATION_S: int = 5 * 60

    # Starting balance for new players
    STARTING_BALANCE: int = 5000


ECONOMY = EconomyConfig()
