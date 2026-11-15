import asyncio
import logging
import os

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from dotenv import load_dotenv
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import engine
from app.models.order import Order
from app.models.user import User
from app.workers.base import PermanentError, run_consumer

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notification-worker")

QUEUE_NAME = "notification.order_events"

tg_bot = Bot(token=os.getenv("BOT_TOKEN"))

MESSAGES = {
    "paid": "Order #{id} has been paid. Amount: {total}.",
    "failed": "Payment for order #{id} did not go through. Please try placing the order again.",
}


class OrderNotFound(PermanentError):
    """There is no order with this ID; repeating the request is pointless.."""


async def handle_notification(data: dict, db_engine=engine):
    try:
        order_id = int(data["order_id"])
    except (KeyError, TypeError, ValueError):
        raise PermanentError("invalid message")

    # read the order and user info, then close the session: while we wait for Telegram, the connection to the database cannot be occupied
    async with AsyncSession(db_engine) as session:
        result = await session.execute(
            select(Order, User).join(User, Order.user_id == User.id).where(Order.id == order_id)
        )
        row = result.first()
        if row is None:
            raise OrderNotFound(order_id)
        order, user = row
        status, total = order.status, order.total_amount
        user_id, chat_id = user.id, user.telegram_chat_id

    template = MESSAGES.get(status)
    if template is None:
        logger.info("Order %s has status %s, nothing to announce", order_id, status)
        return
    if chat_id is None:
        logger.info("User %s has no Telegram linked, skipping order %s", user_id, order_id)
        return

    try:
        await tg_bot.send_message(chat_id, template.format(id=order_id, total=total))
    except TelegramForbiddenError:
        logger.warning("User %s blocked the bot, unlinking chat %s", user_id, chat_id)
        async with AsyncSession(db_engine) as session:
            await session.execute(
                update(User).where(User.id == user_id).values(telegram_chat_id=None)
            )
            await session.commit()
        return
    except TelegramBadRequest as exc:
        raise PermanentError(f"telegram rejected the message: {exc}")

    logger.info("Notified user %s about order %s (%s)", user_id, order_id, status)


async def main():
    try:
        await run_consumer(QUEUE_NAME, handle_notification)
    finally:
        await tg_bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass