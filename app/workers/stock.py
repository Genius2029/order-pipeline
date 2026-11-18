import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import engine
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.workers.base import PermanentError, run_worker
from app.workers.dedupe import mark_processed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stock-worker")

CONSUMER = "stock"
QUEUE_NAME = "stock.order_failed"


class OrderNotFound(PermanentError):
    """There is no order with this ID; repeating the request is pointless.."""


async def handle_restock(data: dict, message_id=None, db_engine=engine):
    try:
        order_id = int(data["order_id"])
    except (KeyError, TypeError, ValueError):
        raise PermanentError("invalid message")

    async with AsyncSession(db_engine) as session:
        # "processed" status and return of the remaining balance: ONE transaction
        if message_id and not await mark_processed(session, CONSUMER, message_id):
            logger.info("Duplicate message %s, skipping", message_id)
            return

        result = await session.execute(select(Order.status).where(Order.id == order_id))
        status = result.scalar_one_or_none()
        if status is None:
            raise OrderNotFound(order_id)
        if status != "failed":
            logger.warning("Order %s is %s, not failed: nothing to release", order_id, status)
            return

        result = await session.execute(
            select(OrderItem.product_id, OrderItem.quantity)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.product_id)     # the same locking order as in the case of a reservation
        )
        items = result.all()

        for product_id, quantity in items:
            await session.execute(
                update(Product)
                .where(Product.id == product_id)
                .values(stock=Product.stock + quantity)
                .execution_options(synchronize_session=False)
            )
        await session.commit()

    logger.info("Restocked order %s (%s items)", order_id, len(items))


if __name__ == "__main__":
    run_worker(QUEUE_NAME, handle_restock)