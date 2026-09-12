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
            text=f"{TIER_LABEL[t['tier']]} · {format_amount(t['price'])} ({t['available']}/{t['total']} left)",
            callback_data=f"shop:tier:{category}:{t['tier']}",
        )]
        for t in tiers
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _item_kb(items: list) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(i), callback_data=f"shop:item:{g.id}")
        for i, g in enumerate(items, start=1) if g.owner_user_id is None
    ]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    return InlineKeyboardMarkup(inline_keyboard=rows)  # empty rows list = no buttons shown, valid when everything's sold


@router.message(Command("shop"))
async def shop_cmd(message: Message):
    async with get_session() as session:
        categories = await get_categories(session)

    if not categories:
        await message.reply("shop's empty right now. check back later.")
        return

    lines = [f"{pe('vip')} <b>PTS SHOP</b>", ""]
    for i, c in enumerate(categories, start=1):
        lines.append(f"{i}. <b>{esc(c['category'])}</b> {raw_tag(c['preview_emoji_id'])}")
    lines.append("")
    lines.append("tap a category.")
    await message.reply("\n".join(lines), reply_markup=_category_kb(categories))


@router.callback_query(F.data.startswith("shop:cat:"))
async def on_category(callback: CallbackQuery):
    category = callback.data.split(":", 2)[2]
    async with get_session() as session:
        categories = await get_categories(session)
        meta = next((c for c in categories if c["category"] == category), None)
        has_tiers = bool(meta and meta["has_tiers"])
        tiers = await get_tiers(session, category) if has_tiers else []

    if has_tiers:
        lines = [f"<b>{esc(category)}</b>", ""]
        for t in tiers:
            lines.append(f"{TIER_LABEL[t['tier']]} · {format_amount(t['price'])} pts each ({t['available']}/{t['total']} left)")
        lines.append("")
        lines.append("tap a tier.")
        await callback.message.edit_text("\n".join(lines), reply_markup=_tier_kb(category, tiers))
    else:
        # Limited Edition -- no tier step, straight to the item list
        await _show_items(callback, category, None)
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
    await callback.message.edit_text("\n".join(lines), reply_markup=_item_kb(items))


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
