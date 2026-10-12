"""
Owner-only migration tools (see services/maintenance.py):
  /ledgerfix   preview + confirm button, records unrecorded balance changes
  /giftpayout  preview + confirm button, takes old gifts and pays half of worth

Everyone else is ignored silently, same as the other owner commands.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.config import settings
from app.database.db import get_session
from app.database.models import User
from app.services.economy_report import short
from app.services.maintenance import (
    MaintenanceError, apply_ledger_fix, plan_ledger_fix, plan_legacy_payout, run_legacy_payout,
)
from app.utils.html_esc import esc

router = Router()


def _is_owner(user_id: int) -> bool:
    return user_id in settings.owner_id_set


async def _names(session, ids) -> dict:
    if not ids:
        return {}
    rows = (await session.execute(select(User).where(User.id.in_(list(ids))))).scalars()
    return {u.id: u.display_name for u in rows}


# ------------------------------------------------------------------ ledger fix

@router.message(Command("ledgerfix"), F.chat.type.in_({"group", "supergroup"}))
async def ledgerfix(message: Message):
    if not _is_owner(message.from_user.id):
        return
    async with get_session() as session:
        plan = await plan_ledger_fix(session)
        names = await _names(session, [r[0] for r in plan.rows[:5]])
    if not plan.rows:
        await message.reply("Ledger already matches every wallet.")
        return
    lines = [
        "<b>Ledger correction · preview</b>",
        f"{len(plan.rows)} wallets differ · total {short(plan.total)}",
        f"Starting balances never recorded: {plan.n_start} wallets · {short(plan.start_total)}",
        f"Unexplained rest: {short(plan.unexplained)}",
        "Adds ledger rows only. Balances do not change.",
        "",
    ]
    for uid, bal, led, diff in plan.rows[:5]:
        lines.append(f"{esc(names.get(uid, str(uid)))}: {short(diff)}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Apply correction", callback_data=f"lfix:{plan.token}")
    ]])
    await message.reply("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("lfix:"))
async def ledgerfix_apply(callback: CallbackQuery):
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    token = callback.data.split(":", 1)[1]
    try:
        async with get_session() as session:
            plan = await apply_ledger_fix(session, token)
    except MaintenanceError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.message.edit_text(
        f"<b>Ledger corrected</b>\n{len(plan.rows)} wallets · total {short(plan.total)}\nBalances unchanged."
    )
    await callback.answer("Done")


# ---------------------------------------------------------------- gift payout

@router.message(Command("giftpayout"), F.chat.type.in_({"group", "supergroup"}))
async def giftpayout(message: Message):
    if not _is_owner(message.from_user.id):
        return
    async with get_session() as session:
        plan = await plan_legacy_payout(session)
        top = sorted(plan.refunds.items(), key=lambda kv: kv[1], reverse=True)[:5]
        names = await _names(session, [uid for uid, _ in top])
    if plan.n_owned + plan.n_stock == 0:
        await message.reply("No old gifts left. Nothing to pay.")
        return
    on = settings.gift_economy
    lines = [
        "<b>Old gift payout · preview</b>",
        f"{plan.n_owned} owned gifts · {len(plan.refunds)} players",
        f"Worth {short(plan.total_worth)} → pays <b>{short(plan.total_refund)}</b> (half)",
        f"Unsold stock archived: {plan.n_stock} · equipped badges cleared: {plan.n_equipped}",
        "Streak badges stay.",
    ]
    if top:
        lines.append("")
        lines += [f"{esc(names.get(uid, str(uid)))}: {plan.counts[uid]} gifts → {short(amt)}" for uid, amt in top]
    if plan.warnings:
        lines += ["", "Odd rows (still paid and archived):"] + [f"• {esc(w)}" for w in plan.warnings]
    lines += ["", f"GIFT_ECONOMY is <b>{'on' if on else 'off'}</b>."]
    kb = None
    if on:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Run payout (cannot undo)", callback_data=f"gpay:{plan.token}")
        ]])
    else:
        lines.append("Set GIFT_ECONOMY=on to unlock the button.")
    await message.reply("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("gpay:"))
async def giftpayout_run(callback: CallbackQuery):
    if not _is_owner(callback.from_user.id):
        await callback.answer()
        return
    if not settings.gift_economy:
        await callback.answer("GIFT_ECONOMY is off.", show_alert=True)
        return
    token = callback.data.split(":", 1)[1]
    try:
        async with get_session() as session:
            plan = await run_legacy_payout(session, token)
    except MaintenanceError as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.message.edit_text(
        f"<b>Payout done</b>\n{plan.n_owned} gifts taken · {len(plan.refunds)} players paid {short(plan.total_refund)}\n"
        f"{plan.n_stock} unsold archived. Old emoji ids saved."
    )
    await callback.answer("Done")
