"""
/shop -- the pts sink + flex system. Flow: categories -> (tier, if the
category has one) -> numbered items -> tap to buy. Every step is buttons,
not typed input (consistent with every other choice in the bot, and more
reliable in a busy group chat than parsing free text).

/addgift is the owner-only restock tool. /equip lets a player pick which
OWNED gift displays as their badge (see gifts.badge_tag, shown in /stats,
/bal, /top, /gtop).
"""
import random

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from app.config import settings
from app.database.db import get_session
from app.services.economy import get_or_create_user, get_or_create_state, format_amount, parse_amount, InvalidAmount
from app.services.gifts import get_categories, get_tiers, get_items, get_gift, purchase_gift, player_cabinet, GiftError
from app.services.premium_emoji import pe, raw_tag
from app.utils.html_esc import esc

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

TIER_LABEL = {"low": "Low", "mid": "Mid", "high": "High"}
TROLL_LINES = [
    "lol you thought? go run a few more /hunt first.",
    "bro checked his balance and still pressed buy 💀",
    "that's cute. come back when you have that much.",
    "the audacity. you're nowhere close.",
    "not happening on that balance, champ.",
]


def _category_kb(categories: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{i}. {c['category']}", callback_data=f"shop:cat:{c['category']}")]
        for i, c in enumerate(categories, start=1)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tier_kb(category: str, tiers: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            # Plain f"{n:,}" here, NOT format_amount() -- that embeds a
            # <tg-emoji> tag for the pts symbol, which is fine in message
            # text but buttons only render plain text, so the raw tag
            # would show up literally instead of rendering as an emoji.
            text=f"{TIER_LABEL[t['tier']]} · {t['price']:,} ({t['available']}/{t['total']} left)",
            callback_data=f"shop:tier:{category}:{t['tier']}",
        )]
        for t in tiers
    ]
    rows.append([InlineKeyboardButton(text="« back", callback_data="shop:back:categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _item_kb(items: list, category: str, tier: str | None) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(i), callback_data=f"shop:item:{g.id}")
        for i, g in enumerate(items, start=1) if g.owner_user_id is None
    ]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    # Tiered category -> back goes to its tier list. Limited Edition (no
    # tier step at all) -> back goes straight to categories.
    back_cb = f"shop:back:tier:{category}" if tier else "shop:back:categories"
    rows.append([InlineKeyboardButton(text="« back", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _categories_view(categories: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    lines = [f"{pe('vip')} <b>PTS SHOP</b>", ""]
    for i, c in enumerate(categories, start=1):
        lines.append(f"{i}. <b>{esc(c['category'])}</b> {raw_tag(c['preview_emoji_id'])}")
    lines.append("")
    lines.append("tap a category.")
    return "\n".join(lines), _category_kb(categories)


def _tiers_view(category: str, tiers: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    lines = [f"<b>{esc(category)}</b>", ""]
    for t in tiers:
        lines.append(f"{TIER_LABEL[t['tier']]} · {format_amount(t['price'])} pts each ({t['available']}/{t['total']} left)")
    lines.append("")
    lines.append("tap a tier.")
    return "\n".join(lines), _tier_kb(category, tiers)


@router.message(Command("shop"))
async def shop_cmd(message: Message):
    async with get_session() as session:
        categories = await get_categories(session)

    if not categories:
        await message.reply("shop's empty right now. check back later.")
        return

    text, kb = _categories_view(categories)
    await message.reply(text, reply_markup=kb)


@router.callback_query(F.data == "shop:back:categories")
async def on_back_categories(callback: CallbackQuery):
    async with get_session() as session:
        categories = await get_categories(session)
    if not categories:
        await callback.message.edit_text("shop's empty right now. check back later.")
    else:
        text, kb = _categories_view(categories)
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:cat:"))
async def on_category(callback: CallbackQuery):
    category = callback.data.split(":", 2)[2]
    async with get_session() as session:
        categories = await get_categories(session)
        meta = next((c for c in categories if c["category"] == category), None)
        has_tiers = bool(meta and meta["has_tiers"])
        tiers = await get_tiers(session, category) if has_tiers else []

    if has_tiers:
        text, kb = _tiers_view(category, tiers)
        await callback.message.edit_text(text, reply_markup=kb)
    else:
        # Limited Edition -- no tier step, straight to the item list
        await _show_items(callback, category, None)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:back:tier:"))
async def on_back_tier(callback: CallbackQuery):
    category = callback.data.split(":", 3)[3]
    async with get_session() as session:
        tiers = await get_tiers(session, category)
    text, kb = _tiers_view(category, tiers)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:tier:"))
async def on_tier(callback: CallbackQuery):
    _, _, category, tier = callback.data.split(":", 3)
    await _show_items(callback, category, tier)
    await callback.answer()


async def _show_items(callback: CallbackQuery, category: str, tier: str | None):
    async with get_session() as session:
        items = await get_items(session, category, tier)

    label = f"{esc(category)} · {TIER_LABEL[tier]}" if tier else esc(category)
    lines = [f"<b>{label}</b>", ""]
    for i, g in enumerate(items, start=1):
        tag = raw_tag(g.emoji_id)
        if g.owner_user_id is not None:
            lines.append(f"{i}. {tag} <s>SOLD</s>")
        else:
            lines.append(f"{i}. {tag} · {format_amount(g.price)} pts")
    lines.append("")
    lines.append("tap a number to buy.")
    await callback.message.edit_text("\n".join(lines), reply_markup=_item_kb(items, category, tier))


@router.callback_query(F.data.startswith("shop:item:"))
async def on_item(callback: CallbackQuery):
    gift_id = int(callback.data.split(":", 2)[2])
    user = callback.from_user

    async with get_session() as session:
        await get_or_create_user(session, user.id, user.full_name, user.username)
        state = await get_or_create_state(session, user.id, callback.message.chat.id)
        gift = await get_gift(session, gift_id)
        if gift is None:
            await callback.answer("that gift doesn't exist anymore.", show_alert=True)
            return
        try:
            await purchase_gift(session, state, gift, callback.message.chat.id)
        except GiftError as e:
            if str(e) == "sold":
                await callback.answer("too slow, someone already grabbed that one.", show_alert=True)
            else:
                await callback.answer(random.choice(TROLL_LINES), show_alert=True)
            return

    await callback.answer("sold! check your DMs... just kidding, check below.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(raw_tag(gift.emoji_id))
    await callback.message.answer(
        f"{pe('gg')} <b>{esc(user.full_name)}</b> just copped it. added to your /stats cabinet forever."
    )


@router.message(Command("equip"))
async def equip_cmd(message: Message):
    async with get_session() as session:
        user = message.from_user
        await get_or_create_user(session, user.id, user.full_name, user.username)
        owned = await player_cabinet(session, user.id)

    if not owned:
        await message.reply("you don't own any gifts yet. check /shop.")
        return

    rows = [
        [InlineKeyboardButton(text=f"{i}", callback_data=f"equip:{g.id}")]
        for i, g in enumerate(owned, start=1)
    ]
    rows.append([InlineKeyboardButton(text="remove badge", callback_data="equip:none")])
    lines = ["pick a badge to display next to your name:", ""]
    for i, g in enumerate(owned, start=1):
        lines.append(f"{i}. {raw_tag(g.emoji_id)} ({esc(g.category)})")
    await message.reply("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("equip:"))
async def on_equip(callback: CallbackQuery):
    choice = callback.data.split(":", 1)[1]
    user = callback.from_user

    async with get_session() as session:
        state = await get_or_create_state(session, user.id, callback.message.chat.id)
        if choice == "none":
            state.equipped_gift_id = None
            await callback.answer("badge removed.")
        else:
            gift_id = int(choice)
            owned = await player_cabinet(session, user.id)
            if gift_id not in [g.id for g in owned]:
                await callback.answer("that's not yours.", show_alert=True)
                return
            state.equipped_gift_id = gift_id
            await callback.answer("badge equipped!")

    await callback.message.edit_reply_markup(reply_markup=None)


@router.message(Command("addgift"))
async def addgift_cmd(message: Message):
    """Owner-only restock tool.
    Usage: /addgift <category> | <tier or -> | <price> | <emoji_id> [emoji_id2 ...]
    Example: /addgift Snoop Cars | low | 25000000 | 5375493278542099683 5379633584065770269
    Use '-' for tier on a Limited Edition category (no tiers)."""
    if message.from_user.id not in settings.owner_id_set:
        return  # silently ignore -- no error text, so it doesn't hint the command exists

    raw = message.text.split(maxsplit=1)
    if len(raw) < 2 or "|" not in raw[1]:
        await message.reply(
            "usage: /addgift &lt;category&gt; | &lt;tier or -&gt; | &lt;price&gt; | &lt;emoji_id&gt; [more ids...]\n"
            "example: /addgift Snoop Cars | low | 25000000 | 5375493278542099683 5379633584065770269"
        )
        return

    parts = [p.strip() for p in raw[1].split("|")]
    if len(parts) != 4:
        await message.reply("need exactly 4 parts separated by | -- category, tier, price, emoji id(s).")
        return

    category, tier_raw, price_raw, ids_raw = parts
    tier = None if tier_raw in ("-", "none", "") else tier_raw.lower()
    try:
        price = parse_amount(price_raw)
    except InvalidAmount as e:
        await message.reply(f"bad price: {e}")
        return

    emoji_ids = ids_raw.split()
    if not emoji_ids:
        await message.reply("no emoji ids given.")
        return

    from app.database.models import Gift
    async with get_session() as session:
        for eid in emoji_ids:
            session.add(Gift(category=category, tier=tier, emoji_id=eid, price=price))

    await message.reply(f"added {len(emoji_ids)} gift(s) to {esc(category)} ({tier or 'limited'}).")
             
