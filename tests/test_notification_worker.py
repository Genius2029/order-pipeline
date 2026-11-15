from datetime import datetime, timedelta, timezone

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.bot.main import consume_link_code
from app.models.telegram_link_code import TelegramLinkCode
from app.models.user import User
from app.workers import notification
from app.workers.base import PermanentError


class FakeBot:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    async def send_message(self, chat_id, text):
        if self.error:
            raise self.error
        self.sent.append((chat_id, text))


async def test_paid_order_sends_notification(engine, make_order, monkeypatch):
    _, order_id = await make_order(status="paid", chat_id=777)
    fake = FakeBot()
    monkeypatch.setattr(notification, "tg_bot", fake)

    await notification.handle_notification({"order_id": order_id}, db_engine=engine)

    assert len(fake.sent) == 1
    chat_id, text = fake.sent[0]
    assert chat_id == 777
    assert str(order_id) in text


async def test_user_without_telegram_gets_nothing(engine, make_order, monkeypatch):
    _, order_id = await make_order(status="paid", chat_id=None)
    fake = FakeBot()
    monkeypatch.setattr(notification, "tg_bot", fake)

    await notification.handle_notification({"order_id": order_id}, db_engine=engine)

    assert fake.sent == []


async def test_blocked_bot_unlinks_user(engine, make_order, monkeypatch):
    user_id, order_id = await make_order(status="paid", chat_id=777)
    error = TelegramForbiddenError(method=None, message="Forbidden: bot was blocked by the user")
    monkeypatch.setattr(notification, "tg_bot", FakeBot(error=error))

    await notification.handle_notification({"order_id": order_id}, db_engine=engine)

    async with AsyncSession(engine) as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id is None


async def test_link_code_works_only_once(engine, make_order):
    user_id, _ = await make_order()
    async with AsyncSession(engine) as session:
        session.add(
            TelegramLinkCode(
                code="abc123",
                user_id=user_id,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        )
        await session.commit()

    assert await consume_link_code("abc123", 555, db_engine=engine) is True
    assert await consume_link_code("abc123", 555, db_engine=engine) is False

    async with AsyncSession(engine) as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id == 555


async def test_expired_link_code_is_rejected(engine, make_order):
    user_id, _ = await make_order()
    async with AsyncSession(engine) as session:
        session.add(
            TelegramLinkCode(
                code="old",
                user_id=user_id,
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await session.commit()

    assert await consume_link_code("old", 555, db_engine=engine) is False

    async with AsyncSession(engine) as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id is None


async def test_bad_request_is_permanent_and_keeps_link(engine, make_order, monkeypatch):
    user_id, order_id = await make_order(status="paid", chat_id=777)
    error = TelegramBadRequest(method=None, message="Bad Request: chat not found")
    monkeypatch.setattr(notification, "tg_bot", FakeBot(error=error))

    with pytest.raises(PermanentError):
        await notification.handle_notification({"order_id": order_id}, db_engine=engine)

    async with AsyncSession(engine) as session:
        user = await session.get(User, user_id)
        assert user.telegram_chat_id == 777


async def test_telegram_link_endpoint_creates_code(api, engine, user_headers):
    response = await api.post("/me/telegram-link", headers=user_headers)

    assert response.status_code == 200
    link = response.json()["link"]
    assert "t.me/" in link
    code = link.split("start=")[1]

    async with AsyncSession(engine) as session:
        rows = (await session.execute(select(TelegramLinkCode))).scalars().all()
    assert len(rows) == 1
    assert rows[0].code == code


async def test_telegram_link_requires_login(api):
    response = await api.post("/me/telegram-link")

    assert response.status_code in (401, 403)