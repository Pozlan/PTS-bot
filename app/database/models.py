"""
Every economic entity is scoped by group_id except the User row itself
(a Telegram user's identity is global, their balance/stats are not).
This is what makes "group has its own economy" (spec section 28) hold:
a PlayerState is unique per (user_id, group_id).
"""
from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String,
    UniqueConstraint, Index, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.time import utcnow


class Base(DeclarativeBase):
    pass


class User(Base):
    """Global Telegram user identity — no balance here."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram user id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram chat id
    title: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class GroupSettings(Base):
    """Admin-configurable overrides (spec section 29). NULL means 'use default'."""
    __tablename__ = "group_settings"

    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), primary_key=True)
    games_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pvp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    robbery_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    economy_multiplier: Mapped[float] = mapped_column(Float, default=1.0)


class PlayerState(Base):
    """The per-group wallet + streak state. This is the row that matters most —
    every balance mutation goes through economy.py against this table."""
    __tablename__ = "player_state"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_player_group"),
        Index("ix_player_group_balance", "group_id", "balance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))

    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0)  # locked in open challenges

    win_streak: Mapped[int] = mapped_column(Integer, default=0)
    loss_streak: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)

    robberies_success: Mapped[int] = mapped_column(Integer, default=0)
    robberies_failed: Mapped[int] = mapped_column(Integer, default=0)
    times_robbed: Mapped[int] = mapped_column(Integer, default=0)
    total_wagered: Mapped[int] = mapped_column(BigInteger, default=0)

    # Auto grace period after being successfully robbed -- blocks ANY
    # robber, not just the one who hit them, so five different players
    # can't pile onto the same unprotected victim back-to-back. See
    # config.ROBBERY_VICTIM_GRACE_S and handlers/social.py::rob.
    robbed_immune_until: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    # Counts successful hits since the last /protect activation. Once it
    # hits config.ROBBERY_MAX_HITS_BEFORE_PROTECTION, this player can't be
    # robbed at all (regardless of grace period above) until they run
    # /protect again, which resets it to 0. See handlers/social.py::rob
    # and handlers/social.py::protect.
    hits_since_protection: Mapped[int] = mapped_column(Integer, default=0)
    # When the player was last successfully robbed. Used to reset
    # hits_since_protection after ECONOMY.ROBBERY_HIT_RESET_S.
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    protected_until: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    door_open_until: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    equipped_gift_id: Mapped[int | None] = mapped_column(ForeignKey("gifts.id"), nullable=True)

    # /streak -- see services/streak.py. Global like everything else on this
    # row (balances went global, see economy.GLOBAL_ID), so a player has
    # exactly one streak across every group, not one per group.
    streak_count: Mapped[int] = mapped_column(Integer, default=0)
    streak_best: Mapped[int] = mapped_column(Integer, default=0)
    last_streak_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    # Highest STREAK_MILESTONES day-count already rewarded, lifetime -- a
    # streak that breaks and later climbs back through the same number
    # does not mint a second badge for it.
    streak_milestone_claimed: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow)


class Cooldown(Base):
    """Generic per-player-per-group-per-action cooldown tracker.
    One row per (user, group, action) — avoids a table per command."""
    __tablename__ = "cooldowns"
    __table_args__ = (UniqueConstraint("user_id", "group_id", "action", name="uq_cooldown"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    group_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(32))
    available_at: Mapped[datetime] = mapped_column(DateTime())


class Challenge(Base):
    """A PvP challenge waiting to be accepted (spec section 13/34).
    Reusable across every PvP game via `game` discriminator."""
    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger)
    game: Mapped[str] = mapped_column(String(16))  # "rps" | "coin" | "dice" | "highlow"
    creator_id: Mapped[int] = mapped_column(BigInteger)
    wager: Mapped[int] = mapped_column(BigInteger)

    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending -> accepted -> resolved | expired | cancelled

    acceptor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime())

    # per-game private state, e.g. {"creator_choice": "rock"} — kept as JSON-ish string
    state: Mapped[str] = mapped_column(String(512), default="{}")


class Transaction(Base):
    """Every balance change, ever. Append-only ledger — never mutated after insert.
    This is what makes balances auditable and lets us prove atomicity held."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(24))  # farm|work|loot|hunt|luck|game|tip|rob|admin
    amount: Mapped[int] = mapped_column(BigInteger)  # signed
    balance_after: Mapped[int] = mapped_column(BigInteger)
    ref: Mapped[str] = mapped_column(String(256), default="")  # freeform context
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class HighLowRun(Base):
    """Solo streak game vs the house — guess higher/lower repeatedly, the
    multiplier compounds each correct guess, cash out anytime or bust and
    lose the wager. No pairing with another player, so this doesn't use
    the Challenge table."""
    __tablename__ = "highlow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    group_id: Mapped[int] = mapped_column(BigInteger)
    wager: Mapped[int] = mapped_column(BigInteger)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    current_card: Mapped[int] = mapped_column(Integer)
    rounds_played: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|cashed|busted
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class Gift(Base):
    """/shop item (spec: pts sink + flex/status system). Each row is a
    single, unique, ONE-OF-ONE unit -- not a 'type' with a quantity. Once
    `owner_user_id` is set the gift is permanently sold and can never be
    bought again, only restocked by the owner via /addgift (a fresh new
    row, not un-selling this one). `tier` is null for Limited Edition
    categories, which skip the low/mid/high tier step entirely."""
    __tablename__ = "gifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "low" | "mid" | "high" | None
    emoji_id: Mapped[str] = mapped_column(String(32))
    price: Mapped[int] = mapped_column(BigInteger)

    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    added_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    # --- new gift economy (added in update 2; old code ignores these) ---
    # Streak badges: earned, never traded. Set True for category "streak".
    soulbound: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which release batch this item came from (NULL for old/legacy gifts).
    release_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Fixed /mog score, set from the OFFICIAL price when the item is released.
    # NULL = not set yet (legacy rows). Never derived from a resale price.
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GameHistory(Base):
    """One row per completed game, used by the response engine for context
    (recent games, opponent history) and by /stats and /gstats."""
    __tablename__ = "game_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger)
    game: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(8))  # "house" | "pvp"
    player_id: Mapped[int] = mapped_column(BigInteger)
    opponent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # None for house
    wager: Mapped[int] = mapped_column(BigInteger)
    result: Mapped[str] = mapped_column(String(8))  # "win" | "loss" | "draw"
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class WordRound(Base):
    """One /word round in one chat. Only one 'active' round per chat at a time."""
    __tablename__ = "word_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True)
    word: Mapped[str] = mapped_column(String(4))
    guesses: Mapped[str] = mapped_column(String(256), default="")  # space-separated, in order
    status: Mapped[str] = mapped_column(String(8), default="active")  # active | solved | failed | gaveup
    solver_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class WordContest(Base):
    """Admin-started timed contest. Solves made before ends_at count for it."""
    __tablename__ = "word_contests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True)
    started_by: Mapped[int] = mapped_column(BigInteger)
    ends_at: Mapped[datetime] = mapped_column(DateTime())
    status: Mapped[str] = mapped_column(String(8), default="active")  # active | ended
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class WordSolve(Base):
    """One row per solved word = 1 point. contest_id is NULL for solves made
    outside a contest (those only count for the all-time board)."""
    __tablename__ = "word_solves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    round_id: Mapped[int] = mapped_column(Integer)
    contest_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class StartedUser(Base):
    """Players who have opened the bot in DM at least once. The start gate
    (services/start_gate.py) blocks everyone else in groups."""
    __tablename__ = "started_users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class GiftRelease(Base):
    """One batch of newly added gifts. The whole batch stays unavailable
    until `goes_live_at` (15 minutes after it was added). Stored in the
    database so a restart or redeploy never loses or resets the timer."""
    __tablename__ = "gift_releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(8))              # "tiered" | "limited"
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | live | cancelled
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    goes_live_at: Mapped[datetime] = mapped_column(DateTime())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    __table_args__ = (Index("ix_gift_releases_status_live", "status", "goes_live_at"),)


class ReleaseAnnouncement(Base):
    """One announcement message per group per release, so it can be edited
    when the batch goes live. A failed pin is stored, never fatal."""
    __tablename__ = "release_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    release_id: Mapped[int] = mapped_column(Integer, ForeignKey("gift_releases.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(String(256), default="")   # send/pin problem, if any
    live_notice_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("release_id", "chat_id", name="uq_announcement_release_chat"),)


class GiftListing(Base):
    """A player's /list offer. `token` is the opaque id used in button
    callback data (never a raw gift id or user text)."""
    __tablename__ = "gift_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(16), unique=True)
    gift_id: Mapped[int] = mapped_column(Integer, ForeignKey("gifts.id"))
    seller_id: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | sold | cancelled | expired
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    buyer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        # An item can have only ONE active listing. The database enforces it,
        # so two requests racing each other cannot both succeed.
        Index(
            "uq_gift_listings_one_active", "gift_id", unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_gift_listings_status_expires", "status", "expires_at"),
    )


class GiftEvent(Base):
    """Append-only ownership/market history for unique gifts. Used for
    audit and for the economy report. Never updated after insert."""
    __tablename__ = "gift_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gift_id: Mapped[int] = mapped_column(Integer, ForeignKey("gifts.id"))
    # release | drop_buy | list | cancel | expire | sale | gift | legacy_retire
    kind: Mapped[str] = mapped_column(String(14))
    from_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    to_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price: Mapped[int] = mapped_column(BigInteger, default=0)
    fee: Mapped[int] = mapped_column(BigInteger, default=0)    # amount burned
    listing_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    __table_args__ = (
        Index("ix_gift_events_gift", "gift_id"),
        Index("ix_gift_events_kind_time", "kind", "created_at"),
    )


class LegacyGift(Base):
    """Copy of every old shop gift taken during the gift-economy migration.
    Keeps the original id, emoji id, tier, price and owner so nothing is lost
    and the old emoji art can be reused in new releases. Never deleted."""
    __tablename__ = "legacy_gifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # old gifts.id
    category: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str | None] = mapped_column(String(8), nullable=True)
    emoji_id: Mapped[str] = mapped_column(String(32))
    price: Mapped[int] = mapped_column(BigInteger)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # NULL = unsold stock
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    added_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    was_equipped: Mapped[bool] = mapped_column(Boolean, default=False)
    refund_amount: Mapped[int] = mapped_column(BigInteger, default=0)   # half of price if it had an owner
    retired_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
