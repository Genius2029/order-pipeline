import json
import logging
import os
import uuid

import aio_pika
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "orders"


QUEUES = {
    "payment.order_created": ["order.created"],
}


class Broker:
    def __init__(self, url: str):
        self.url = url
        self.connection = None
        self.channel = None
        self.exchange = None
        self.queues = {}

    async def start(self):
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=10)

        self.exchange = await self.channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        for queue_name, routing_keys in QUEUES.items():
            queue = await self.channel.declare_queue(queue_name, durable=True)
            for routing_key in routing_keys:
                await queue.bind(self.exchange, routing_key=routing_key)
            self.queues[queue_name] = queue

    async def stop(self):
        if self.connection:
            await self.connection.close()

    async def publish(self, routing_key: str, payload: dict):
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(uuid.uuid4()),
        )
        await self.exchange.publish(message, routing_key=routing_key)
        logger.info("Published %s: %s", routing_key, payload)


broker = Broker(os.getenv("RABBITMQ_URL"))