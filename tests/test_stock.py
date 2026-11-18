import asyncio
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order_item import OrderItem
from app.models.product import Product
from app.workers import stock as stock_worker


async def get_stock(engine, product_id):
    async with AsyncSession(engine) as session:
        return (await session.get(Product, product_id)).stock


async def create_failed_order_with_item(engine, make_order, quantity=3, stock=5):
    _, order_id = await make_order(status="failed")
    async with AsyncSession(engine) as session:
        product = Product(name="Cable", price=Decimal("3.00"), stock=stock)
        session.add(product)
        await session.flush()
        product_id = product.id
        session.add(
            OrderItem(order_id=order_id, product_id=product_id,
                        quantity=quantity, unit_price=Decimal("3.00"))
        )
        await session.commit()
    return order_id, product_id


async def test_order_reserves_stock(api, user_headers, products):
    keyboard = products[0]          # stock 10

    await api.post(
        "/orders",
        json={"items": [{"product_id": keyboard, "quantity": 2}]},
        headers=user_headers,
    )

    assert (await api.get(f"/products/{keyboard}")).json()["stock"] == 8


async def test_not_enough_stock_changes_nothing(api, user_headers, products):
    keyboard, mouse, _ = products   # stock 10, 5

    response = await api.post(
        "/orders",
        json={"items": [
            {"product_id": keyboard, "quantity": 1},
            {"product_id": mouse, "quantity": 5},       # more than available
        ]},
        headers=user_headers,
    )

    assert response.status_code == 400
    # first product was not reserved, second product was not reserved, order was not created
    assert (await api.get(f"/products/{keyboard}")).json()["stock"] == 10
    assert (await api.get("/orders", headers=user_headers)).json() == []


async def test_last_item_is_sold_only_once(api, user_headers, other_user_headers, products):
    monitor = products[2]           # остаток 1
    body = {"items": [{"product_id": monitor, "quantity": 1}]}

    first, second = await asyncio.gather(
        api.post("/orders", json=body, headers=user_headers),
        api.post("/orders", json=body, headers=other_user_headers),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 400]
    assert (await api.get(f"/products/{monitor}")).json()["stock"] == 0


async def test_restock_returns_items(engine, make_order):
    order_id, product_id = await create_failed_order_with_item(engine, make_order)

    await stock_worker.handle_restock({"order_id": order_id}, "m1", db_engine=engine)

    assert await get_stock(engine, product_id) == 8     # 5 + 3


async def test_duplicate_message_restocks_once(engine, make_order):
    order_id, product_id = await create_failed_order_with_item(engine, make_order)

    await stock_worker.handle_restock({"order_id": order_id}, "m1", db_engine=engine)
    await stock_worker.handle_restock({"order_id": order_id}, "m1", db_engine=engine)

    assert await get_stock(engine, product_id) == 8     # not 11, second message was ignored

