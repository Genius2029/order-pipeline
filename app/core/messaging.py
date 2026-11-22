import json
import logging
import os
import uuid

import aio_pika
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "orders"
RETRY_DELAY_MS = 5000               #how much time to wait before retrying a failed message
AUDIT_QUEUE = "audit.order_events"


QUEUES = {
    "payment.order_created": ["order.created"],
    "notification.order_events": ["order.paid", "order.failed"],
    "stock.order_failed": ["order.failed"]
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

            await self.channel.declare_queue(
                f"{queue_name}.retry",
                durable=True,
                arguments={
                    "x-message-ttl": RETRY_DELAY_MS,
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": queue_name,
                },
            )

            await self.channel.declare_queue(f"{queue_name}.dlq", durable=True)

        # Audit queue for storing events that can be viewed in the panel (stores no more than 1000 items and for one hour)
        audit = await self.channel.declare_queue(
            AUDIT_QUEUE,
            durable=True,
            arguments={"x-message-ttl": 3_600_000, "x-max-length": 1000},
        )
        await audit.bind(self.exchange, routing_key="order.*")

    async def stop(self):
        if self.connection:
            await self.connection.close()

    async def publish(self, routing_key: str, payload: dict, message_id: str | None = None):
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=message_id or str(uuid.uuid4()),
        )
        await self.exchange.publish(message, routing_key=routing_key)
        logger.info("Published %s: %s", routing_key, payload)

    @staticmethod
    def _copy(message, headers: dict) -> aio_pika.Message:
        # same message but with new headers, used for retry and dlq
        return aio_pika.Message(
            body=message.body,
            content_type=message.content_type,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=message.message_id,
            headers=headers,
        )

    async def send_to_retry(self, queue_name: str, message, attempt: int):
        await self.channel.default_exchange.publish(
            self._copy(message, {"x-attempt": attempt}),
            routing_key=f"{queue_name}.retry",
        )

    async def send_to_dlq(self, queue_name: str, message, attempt: int, reason: str):
        await self.channel.default_exchange.publish(
            self._copy(message, {"x-attempt": attempt, "x-failure-reason": reason}),
            routing_key=f"{queue_name}.dlq",
        )


broker = Broker(os.getenv("RABBITMQ_URL"))