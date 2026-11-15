import os
from decimal import Decimal

import pytest
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from app.api.main import app
from app.core.security import create_access_token, hash_password
from app.database import get_session
from app.core.messaging import Broker


from app.models.order import Order  
from app.models.order_item import OrderItem 
from app.models.product import Product
from app.models.user import User

load_dotenv()

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
# Ensure that the test database URL is set and points to a test database
assert TEST_DATABASE_URL and TEST_DATABASE_URL.endswith("_test"), (
    "TEST_DATABASE_URL must point to a database whose name ends with _test"
)


@pytest.fixture
async def engine():
    test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def api(engine):
    async def override_get_session():
        async with AsyncSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _create_user(engine, email: str, is_admin: bool = False) -> int:
    async with AsyncSession(engine) as session:
        user = User(
            email=email,
            full_name="Test User",
            hashed_password=hash_password("secret123"),
            is_admin=is_admin,
        )
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()
    return user_id


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


@pytest.fixture
async def user_headers(engine):
    return _headers(await _create_user(engine, "user@test.com"))


@pytest.fixture
async def other_user_headers(engine):
    return _headers(await _create_user(engine, "other@test.com"))


@pytest.fixture
async def admin_headers(engine):
    return _headers(await _create_user(engine, "admin@test.com", is_admin=True))


@pytest.fixture
async def products(engine):
    async with AsyncSession(engine) as session:
        items = [
            Product(name="Keyboard", price=Decimal("19.90"), stock=10),
            Product(name="Mouse", price=Decimal("5.00"), stock=3),
            Product(name="Monitor", price=Decimal("120.00"), stock=1),
        ]
        session.add_all(items)
        await session.flush()
        ids = [p.id for p in items]
        await session.commit()
    return ids


@pytest.fixture(autouse=True)
def fake_broker(monkeypatch):
    published = []

    async def fake_publish(self, routing_key, payload):
        published.append((routing_key, payload))

    monkeypatch.setattr(Broker, "publish", fake_publish)
    return published


@pytest.fixture
async def new_order(engine):
    user_id = await _create_user(engine, "buyer@test.com")
    async with AsyncSession(engine) as session:
        order = Order(user_id=user_id, status="new", total_amount=Decimal("50.00"))
        session.add(order)
        await session.flush()
        order_id = order.id
        await session.commit()
    return order_id


@pytest.fixture
def make_order(engine):
    async def _make(status="new", chat_id=None, total="50.00", email="buyer@test.com"):
        async with AsyncSession(engine) as session:
            user = User(
                email=email,
                full_name="Buyer",
                hashed_password=hash_password("secret123"),
                telegram_chat_id=chat_id,
            )
            session.add(user)
            await session.flush()
            order = Order(user_id=user.id, status=status, total_amount=Decimal(total))
            session.add(order)
            await session.flush()
            ids = (user.id, order.id)
            await session.commit()
        return ids

    return _make