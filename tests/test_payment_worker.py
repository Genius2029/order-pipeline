import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.payments import PaymentDeclined, PaymentGatewayError
from app.models.order import Order
from app.workers import payment as worker


class FakeMessage:
    def __init__(self, body: bytes, headers=None):
        self.body = body
        self.headers = headers or {}
        self.message_id = "test-id"
        self.content_type = "application/json"
        self.acked = False

    async def ack(self):
        self.acked = True


@pytest.fixture
def routed(monkeypatch):
    """Records where the worker sent a message: to the retry queue or to the dlq."""
    result = {"retry": [], "dlq": []}

    async def fake_retry(queue_name, message, attempt):
        result["retry"].append(attempt)

    async def fake_dlq(queue_name, message, attempt, reason):
        result["dlq"].append(reason)

    monkeypatch.setattr(worker.broker, "send_to_retry", fake_retry)
    monkeypatch.setattr(worker.broker, "send_to_dlq", fake_dlq)
    return result


async def test_temporary_error_goes_to_retry(routed, monkeypatch):
    async def failing_process(order_id):
        raise PaymentGatewayError("timeout")

    monkeypatch.setattr(worker, "process_order", failing_process)
    message = FakeMessage(b'{"order_id": 1}')

    await worker.on_message(message)

    assert routed["retry"] == [1]
    assert routed["dlq"] == []
    assert message.acked is True


async def test_third_failure_goes_to_dlq(routed, monkeypatch):
    async def failing_process(order_id):
        raise PaymentGatewayError("timeout")

    monkeypatch.setattr(worker, "process_order", failing_process)
    message = FakeMessage(b'{"order_id": 1}', headers={"x-attempt": 2})

    await worker.on_message(message)

    assert routed["retry"] == []
    assert len(routed["dlq"]) == 1
    assert message.acked is True


async def test_garbage_message_goes_to_dlq(routed):
    message = FakeMessage(b"this is not json")

    await worker.on_message(message)

    assert routed["dlq"] == ["invalid message"]
    assert message.acked is True


async def get_status(engine, order_id):
    async with AsyncSession(engine) as session:
        order = await session.get(Order, order_id)
        return order.status


async def test_successful_payment_marks_order_paid(engine, new_order, fake_broker, monkeypatch):
    async def ok_charge(order_id, amount):
        return None

    monkeypatch.setattr(worker, "charge", ok_charge)

    await worker.process_order(new_order, db_engine=engine)

    assert await get_status(engine, new_order) == "paid"
    assert fake_broker == [("order.paid", {"order_id": new_order})]


async def test_declined_payment_marks_order_failed(engine, new_order, fake_broker, monkeypatch):
    async def declined_charge(order_id, amount):
        raise PaymentDeclined("not enough money")

    monkeypatch.setattr(worker, "charge", declined_charge)

    await worker.process_order(new_order, db_engine=engine)

    assert await get_status(engine, new_order) == "failed"
    assert fake_broker == [("order.failed", {"order_id": new_order})]


async def test_processing_same_order_twice_charges_once(engine, new_order, fake_broker, monkeypatch):
    calls = []

    async def counting_charge(order_id, amount):
        calls.append(order_id)

    monkeypatch.setattr(worker, "charge", counting_charge)

    await worker.process_order(new_order, db_engine=engine)
    await worker.process_order(new_order, db_engine=engine)

    assert len(calls) == 1
    assert fake_broker == [("order.paid", {"order_id": new_order})]


async def test_gateway_error_leaves_order_untouched(engine, new_order, fake_broker, monkeypatch):
    async def broken_charge(order_id, amount):
        raise PaymentGatewayError("timeout")

    monkeypatch.setattr(worker, "charge", broken_charge)

    with pytest.raises(PaymentGatewayError):
        await worker.process_order(new_order, db_engine=engine)

    assert await get_status(engine, new_order) == "new"
    assert fake_broker == []


async def test_missing_order_raises_not_found(engine, fake_broker):
    with pytest.raises(worker.OrderNotFound):
        await worker.process_order(999, db_engine=engine)

    assert fake_broker == []