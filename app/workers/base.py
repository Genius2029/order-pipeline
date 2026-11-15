import asyncio
import json
import logging

from app.core.messaging import broker

logger = logging.getLogger("worker")

MAX_ATTEMPTS = 3


class PermanentError(Exception):
    """Retrying won't help: the message is immediately sent to the "debug queue" (DLQ)."""


def make_on_message(queue_name: str, handler):
    """Collects the message handler: body parsing, retries, DLQ, ack.

    handler(data: dict) raises PermanentError or any other exception."""

    async def on_message(message):
        attempt = int(message.headers.get("x-attempt", 0))

        try:
            data = json.loads(message.body)
            if not isinstance(data, dict):
                raise ValueError("body is not an object")
        except ValueError:
            logger.error("Invalid message body: %r", message.body)
            await broker.send_to_dlq(queue_name, message, attempt, "invalid message")
            await message.ack()
            return

        try:
            await handler(data)
        except PermanentError as exc:
            logger.error("Permanent error: %s", exc)
            await broker.send_to_dlq(queue_name, message, attempt, str(exc))
        except Exception as exc:
            attempt += 1
            if attempt >= MAX_ATTEMPTS:
                logger.error("Giving up after %s attempts: %s", attempt, exc)
                await broker.send_to_dlq(queue_name, message, attempt, f"gave up: {exc}")
            else:
                logger.warning("Attempt %s/%s failed (%s), will retry", attempt, MAX_ATTEMPTS, exc)
                await broker.send_to_retry(queue_name, message, attempt)

        await message.ack()

    return on_message


async def run_consumer(queue_name: str, handler):
    await broker.start()
    try:
        queue = broker.queues[queue_name]
        on_message = make_on_message(queue_name, handler)
        logger.info("Waiting for messages in %s", queue_name)

        async with queue.iterator() as messages:
            async for message in messages:
                try:
                    await on_message(message)
                except Exception:
                    logger.exception("Unexpected failure, returning message to the queue")
                    await message.nack(requeue=True)
    finally:
        await broker.stop()


def run_worker(queue_name: str, handler):
    try:
        asyncio.run(run_consumer(queue_name, handler))
    except KeyboardInterrupt:
        pass