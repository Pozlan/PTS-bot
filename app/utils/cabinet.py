"""
Renders a player's owned gifts as the actual premium-emoji badges, one
tag per gift, for /stats (group version in handlers/wallet.py, DM version
in handlers/inbox.py).

This lives in its own module for one reason: those two /stats handlers
were maintaining the same cabinet-rendering code separately, and they had
already drifted (the DM one had no send fallback at all, so a single bad
emoji ID made it reply with nothing whatsoever). One renderer, both
callers.

Everything here is pure -- no session, no I/O. Pass in the list of Gift
rows from gifts.player_cabinet() and get back HTML lines.
"""
from app.config import ECONOMY
from app.database.models import Gift
from app.services.gifts import TIER_ORDER
from app.services.premium_emoji import pe, raw_tag
from app.utils.html_esc import esc

# emoji ID -> the day count that mints it, reversed out of the config so
# a streak badge in the cabinet can be labelled with the milestone it
# represents ("that 60d one" reads better than an anonymous glyph).
# Built at import; STREAK_MILESTONES is static config, not per-player.
STREAK_BADGE_DAYS: dict[str, int] = {
    emoji_id: days for days, emoji_id in ECONOMY.STREAK_MILESTONES.items()
}


def _group_label(category: str, tier: str | None) -> str:
    if tier:
        return f"{esc(category)} · {esc(tier)}"
    return esc(category)


def render_cabinet(cabinet: list[Gift]) -> list[str]:
    """HTML lines for the gift cabinet block, header included.

    Each owned gift renders as its own <tg-emoji> tag -- the actual badge
    art, not a count. Streak milestone badges additionally carry their
    day count, since those are earned rather than bought and the number
    is the whole point of them.

    Fallback characters matter here: raw_tag()'s inner character is what
    Telegram shows to non-Premium viewers AND what safe_reply's derived
    fallback keeps if a send gets rejected. Streak badges fall back to a
    flame, shop gifts to a wrapped gift.
    """
    if not cabinet:
        return [
            f"{pe('vip')} <b>Gift Cabinet</b>",
            "empty. check /shop and start flexing.",
        ]

    lines = [f"{pe('vip')} <b>Gift Cabinet</b> · {len(cabinet)}"]

    # (category, tier) -> gifts. Grouping on tier as well as category
    # means a Low and a High from the same category don't get flattened
    # into one undifferentiated row of glyphs.
    grouped: dict[tuple[str, str | None], list[Gift]] = {}
    for g in cabinet:
        grouped.setdefault((g.category, g.tier), []).append(g)

    def sort_key(key: tuple[str, str | None]) -> tuple[int, str, int]:
        category, tier = key
        # streak badges last -- they're earned, not bought, so they read
        # as a separate achievement shelf under the purchased stuff.
        return (1 if category == "streak" else 0, category, TIER_ORDER.get(tier, 99))

    for key in sorted(grouped, key=sort_key):
        category, tier = key
        gifts = grouped[key]
        if category == "streak":
            # sort by milestone so the shelf climbs 3d -> 10d -> 30d
            gifts = sorted(gifts, key=lambda g: STREAK_BADGE_DAYS.get(g.emoji_id, 0))
            tags = "  ".join(
                f"{raw_tag(g.emoji_id, '🔥')}{STREAK_BADGE_DAYS[g.emoji_id]}d"
                if g.emoji_id in STREAK_BADGE_DAYS
                else raw_tag(g.emoji_id, "🔥")
                for g in gifts
            )
        else:
            tags = " ".join(raw_tag(g.emoji_id) for g in gifts)
        lines.append(f"{_group_label(category, tier)} ({len(gifts)}): {tags}")

    # Streak badges are minted at price=0 (services/streak.py), so they
    # correctly contribute nothing to cabinet value -- worth is what was
    # actually spent on shop stock.
    worth = sum(g.price for g in cabinet)
    lines.append("")
    lines.append(f"{pe('pts')} <b>Worth:</b> {worth:,}")
    return lines
