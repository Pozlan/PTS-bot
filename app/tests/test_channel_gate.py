"""Channel gate: REQUIRED_CHANNEL makes members-only play in groups."""
import pytest
from aiogram.exceptions import TelegramBadRequest

from app.config import settings
from app.services import start_gate as sg


class FakeMember:
    def __init__(self, status, is_member=True):
        self.status = status
        self.is_member = is_member


class FakeBot:
    def __init__(self, status="left", error=False):
        self.status = status
        self.error = error
        self.calls = 0

    async def get_chat_member(self, chat, user_id):
        self.calls += 1
        if self.error:
            raise TelegramBadRequest(method=None, message="chat not found")
        return FakeMember(self.status)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    sg._member_until.clear()
    monkeypatch.setattr(settings, "required_channel", "@etFeed")
    monkeypatch.setattr(settings, "owner_ids", "1")
    yield
    sg._member_until.clear()


@pytest.mark.asyncio
async def test_member_passes_and_is_cached():
    bot = FakeBot("member")
    assert await sg.is_member(bot, 50)
    assert await sg.is_member(bot, 50)
    assert bot.calls == 1


@pytest.mark.asyncio
async def test_non_member_blocked_and_rechecked():
    bot = FakeBot("left")
    assert not await sg.is_member(bot, 50)
    assert not await sg.is_member(bot, 50)
    assert bot.calls == 2
    bot.status = "member"
    assert await sg.is_member(bot, 50)


@pytest.mark.asyncio
async def test_owner_and_off_switch(monkeypatch):
    bot = FakeBot("left")
    assert await sg.is_member(bot, 1)
    monkeypatch.setattr(settings, "required_channel", "")
    assert await sg.is_member(bot, 50)
    assert bot.calls == 0


@pytest.mark.asyncio
async def test_setup_problem_never_blocks():
    assert await sg.is_member(FakeBot(error=True), 50)


def test_handle_and_link(monkeypatch):
    monkeypatch.setattr(settings, "required_channel", "etFeed")
    assert sg.channel_handle() == "@etFeed"
    assert sg.channel_link() == "https://t.me/etFeed"
