import asyncio
import json
import logging

import aio_pika
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.messaging import broker
from app.core.payments import PaymentDeclined, charge
from app.database import engine
from app.models.order import Order

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payment-worker")

QUEUE_NAME = "payment.order_created"
MAX_ATTEMPTS = 3


class OrderNotFound(Exception):
    """Persistent error: no order with this ID exists; retrying is pointless.."""


async def process_order(order_id: int, db_engine=engine):
    # 1. read the order and immediately close the session: while we wait for the external gateway,
    #    the connection to the database cannot be occupied
    async with AsyncSession(db_engine) as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalars().first()
        if order is None:
            raise OrderNotFound(order_id)
        if order.status != "new":
            logger.info("Order %s already processed (%s), skipping", order_id, order.status)
            return
        amount = order.total_amount

    # 2. external call (may fail with PaymentGatewayError, then retry will be triggered)
    try:
        await charge(order_id, amount)
        new_status, event = "paid", "order.paid"
    except PaymentDeclined as exc:
        logger.info("Order %s declined: %s", order_id, exc)
        new_status, event = "failed", "order.failed"

    # 3. change the status with a single conditional query: will only work if the order
    #    is still "new". This is the idempotency at the database level
    async with AsyncSession(db_engine) as session:
        result = await session.execute(
            update(Order)
            .where(Order.id == order_id, Order.status == "new")
            .values(status=new_status)
        )
        await session.commit()
        changed = result.rowcount

    if changed == 0:
        logger.info("Order %s was processed concurrently, nothing to do", order_id)
        return

    # 4. inform all interested parties about the result
    await broker.publish(event, {"order_id": order_id})
    logger.info("Order %s -> %s", order_id, new_status)


async def on_message(message: aio_pika.abc.AbstractIncomingMessage):
    attempt = int(message.headers.get("x-attempt", 0))    # how many times we've already tried

    try:
        order_id = int(json.loads(message.body)["order_id"])
    except (ValueError, KeyError, TypeError):
        logger.error("Invalid message body: %r", message.body)
        await broker.send_to_dlq(QUEUE_NAME, message, attempt, "invalid message")
        await message.ack()
        return

    try:
        await process_order(order_id)
    except OrderNotFound:
        logger.error("Order %s not found", order_id)
        await broker.send_to_dlq(QUEUE_NAME, message, attempt, f"order {order_id} not found")
    except Exception as exc:
        attempt += 1
        if attempt >= MAX_ATTEMPTS:
            logger.error("Order %s: giving up after %s attempts (%s)", order_id, attempt, exc)
            await broker.send_to_dlq(QUEUE_NAME, message, attempt, f"gave up: {exc}")
        else:
            logger.warning(
                "Order %s: attempt %s/%s failed (%s), will retry",
                order_id, attempt, MAX_ATTEMPTS, exc,
            )
            await broker.send_to_retry(QUEUE_NAME, message, attempt)

    await message.ack()


async def main():
    await broker.start()
    try:
        queue = broker.queues[QUEUE_NAME]
        logger.info("Waiting for messages in %s", QUEUE_NAME)

        async with queue.iterator() as messages:
            async for message in messages:
                try:
                    await on_message(message)
                except Exception:
                    # emergency case (e.g., broker unavailable): return to queue
                    logger.exception("Unexpected failure, returning message to the queue")
                    await message.nack(requeue=True)
    finally:
        await broker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass