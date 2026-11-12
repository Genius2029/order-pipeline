import asyncio
import json
import logging

from app.core.messaging import broker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payment-worker")

QUEUE_NAME = "payment.order_created"


async def handle_order_created(data: dict):
    logger.info("Got order.created: order_id=%s", data["order_id"])


async def main():
    await broker.start()
    try:
        queue = broker.queues[QUEUE_NAME]
        logger.info("Waiting for messages in %s", QUEUE_NAME)

        async with queue.iterator() as messages:
            async for message in messages:
                async with message.process():
                    data = json.loads(message.body)
                    await handle_order_created(data)
    finally:
        await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
