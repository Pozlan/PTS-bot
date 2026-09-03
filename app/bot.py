import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from app.config import settings
from app.database.db import init_db
from app.handlers import economy, wallet, social, rps, coin, dice, highlow, pvp_common, admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ptsbot")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(wallet.router)
    dp.include_router(economy.router)
    dp.include_router(social.router)
    dp.include_router(rps.router)
    dp.include_router(coin.router)
    dp.include_router(dice.router)
    dp.include_router(highlow.router)
    dp.include_router(admin.router)
    dp.include_router(pvp_common.router)  # owns "acc:", "vsbot:", "coin:" callbacks for all games
    return dp


async def _run_health_server() -> None:
    """Render's free tier is Web Service only — Background Workers have no
    free instance type. Running a bot with long-polling doesn't need an
    inbound port at all, but binding one anyway is what makes Render treat
    this as a (free) Web Service instead of a (paid, $7/mo+) Background
    Worker. Same trick already used for PozzCapital's Render deploy.

    Note: Render's free Web Services still spin down after 15 minutes with
    no INBOUND HTTP traffic — the bot's own outbound polling to Telegram
    doesn't count. Point an uptime pinger (e.g. UptimeRobot, free) at this
    service's URL every 5-10 minutes to keep it awake 24/7."""
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="ptsbot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"health check server listening on port {port}")


async def run() -> None:
    await init_db()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    await _run_health_server()
    logger.info("ptsbot starting polling")
    await dp.start_polling(bot)
