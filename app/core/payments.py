import asyncio
import logging
import os
import random
from decimal import Decimal

logger = logging.getLogger(__name__)

# proportion of temporary failures; for experiments: 0 - never, 1 - always
TRANSIENT_ERROR_RATE = float(os.getenv("PAYMENT_ERROR_RATE", "0.3"))
DECLINE_THRESHOLD = Decimal("1000")     # orders of 1000 or more are being "declined by the bank"


class PaymentDeclined(Exception):
    """The bank said no: a standard business outcome—trying again won’t help."""


class PaymentGatewayError(Exception):
    """A temporary failure in the payment gateway: a retry might help."""

async def charge(order_id: int, amount: Decimal) -> None:
    # Actual payment gateways accept such an "idempotency key":
    # repeat request with the same key does not result in a second charge.
    idempotency_key = f"order-{order_id}"

    await asyncio.sleep(0.5)    # network call simulation

    if random.random() < TRANSIENT_ERROR_RATE:
        raise PaymentGatewayError(f"gateway timeout (key={idempotency_key})")
    if amount >= DECLINE_THRESHOLD:
        raise PaymentDeclined(f"card declined for amount {amount}")

    logger.info("Charged %s for order %s (key=%s)", amount, order_id, idempotency_key)