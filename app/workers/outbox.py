import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.messaging import broker
from app.database import engine
from app.models.outbox_event import OutboxEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox-relay")

POLL_INTERVAL = 1.0     


async def relay_once(db_engine=engine) -> bool:
    """Publishes one unsent event. True means something was sent."""
    async with AsyncSession(db_engine) as session:
        result = await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        event = result.scalars().first()
        if event is None:
            return False

        # We take the values ​​BEFORE the commit: after it, the object is "stale."
        routing_key, payload, message_id = event.routing_key, event.payload, event.message_id

        await broker.publish(routing_key, payload, message_id=message_id)

        event.published_at = datetime.now(timezone.utc)
        session.add(event)
        await session.commit()

    logger.info("Relayed %s (%s)", routing_key, message_id)
    return True


async def main():
    await broker.start()
    logger.info("Outbox relay started")
    try:
        while True:
            try:
                sent = await relay_once()
            except Exception:
                logger.exception("Relay failed, will retry")
                sent = False
            if not sent:
                await asyncio.sleep(POLL_INTERVAL)
    finally:
        await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass