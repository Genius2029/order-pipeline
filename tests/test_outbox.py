import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.messaging import Broker
from app.models.outbox_event import OutboxEvent
from app.workers.outbox import relay_once


async def add_event(engine, routing_key="order.created", payload=None):
    async with AsyncSession(engine) as session:
        event = OutboxEvent(routing_key=routing_key, payload=payload or {"order_id": 1})
        session.add(event)
        await session.flush()
        event_id, message_id = event.id, event.message_id
        await session.commit()
    return event_id, message_id


async def get_event(engine, event_id):
    async with AsyncSession(engine) as session:
        return await session.get(OutboxEvent, event_id)


async def test_relay_publishes_event_and_marks_it(engine, monkeypatch):
    event_id, message_id = await add_event(engine)
    seen = []

    async def recording_publish(self, routing_key, payload, message_id=None):
        seen.append((routing_key, payload, message_id))

    monkeypatch.setattr(Broker, "publish", recording_publish)

    assert await relay_once(db_engine=engine) is True
    assert seen == [("order.created", {"order_id": 1}, message_id)]    # stable message_id
    assert (await get_event(engine, event_id)).published_at is not None

    assert await relay_once(db_engine=engine) is False                 # There's nothing to send a second time
    assert len(seen) == 1


async def test_failed_publish_keeps_event_for_retry(engine, monkeypatch):
    event_id, _ = await add_event(engine)

    async def broken_publish(self, routing_key, payload, message_id=None):
        raise ConnectionError("rabbitmq is down")

    monkeypatch.setattr(Broker, "publish", broken_publish)

    with pytest.raises(ConnectionError):
        await relay_once(db_engine=engine)

    assert (await get_event(engine, event_id)).published_at is None    # the event is not lost