"""
Every economic entity is scoped by group_id except the User row itself
(a Telegram user's identity is global, their balance/stats are not).
This is what makes "group has its own economy" (spec section 28) hold:
a PlayerState is unique per (user_id, group_id).
"""
from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String,
    UniqueConstraint, Index,
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

    protected_until: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    door_open_until: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

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
