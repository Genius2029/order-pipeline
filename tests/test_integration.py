import json
import os

import pytest

from app.core.messaging import Broker

pytestmark = pytest.mark.integration

QUEUE = "payment.order_created"


async def test_event_reaches_payment_queue():
    broker = Broker(os.getenv("RABBITMQ_URL"))
    await broker.start()
    try:
        # if a worker is subscribed to the queue, it will pick up the message before the test
        probe = await broker.channel.declare_queue(QUEUE, passive=True)
        if probe.declaration_result.consumer_count > 0:
            pytest.skip("Workers are consuming payment.order_created: stop them and re-run")

        queue = broker.queues[QUEUE]
        await queue.purge()

        await broker.publish("order.created", {"order_id": 123}, message_id="it-1")

        message = await queue.get(timeout=5)
        async with message.process():
            assert json.loads(message.body) == {"order_id": 123}
            assert message.message_id == "it-1"
    finally:
        await broker.stop()