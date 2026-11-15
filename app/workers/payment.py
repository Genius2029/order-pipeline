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
from app.workers.base import PermanentError, make_on_message, run_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payment-worker")

QUEUE_NAME = "payment.order_created"
MAX_ATTEMPTS = 3


class OrderNotFound(PermanentError):
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


async def handle_payment(data: dict):
    try:
        order_id = int(data["order_id"])
    except (KeyError, TypeError, ValueError):
        raise PermanentError("invalid message")
    await process_order(order_id)


on_message = make_on_message(QUEUE_NAME, handle_payment)


if __name__ == "__main__":
    run_worker(QUEUE_NAME, handle_payment)