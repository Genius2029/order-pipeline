import json
import os

import pytest

from app.core.messaging import Broker

pytestmark = pytest.mark.integration


async def test_event_reaches_payment_queue():
    broker = Broker(os.getenv("RABBITMQ_URL"))
    await broker.start()
    try:
        queue = broker.queues["payment.order_created"]
        await queue.purge()

        await broker.publish("order.created", {"order_id": 123}, message_id="it-1")

        message = await queue.get(timeout=5)
        async with message.process():
            assert json.loads(message.body) == {"order_id": 123}
            assert message.message_id == "it-1"
    finally:
        await broker.stop()