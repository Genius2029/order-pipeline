from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user
from app.database import get_session
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.user import User
from app.schemas.order import (
    OrderCreate,
    OrderItemRead,
    OrderRead,
    OrderSummary,
)

import logging

from app.core.messaging import broker

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/orders", response_model=OrderRead, status_code=201)
async def create_order(
    data: OrderCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # 1. merging duplicates: same item appears twice -> combine the quantities
    quantities: dict[int, int] = {}
    for item in data.items:
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity

    # 2. retrieve items in a single request
    result = await session.execute(select(Product).where(Product.id.in_(list(quantities))))
    products = {p.id: p for p in result.scalars().all()}

    missing = set(quantities) - set(products)
    if missing:
        raise HTTPException(status_code=404, detail=f"Products not found: {sorted(missing)}")

    # 3. check the remaining stock and calculate the total value based on prices FROM THE DATABASE
    total = Decimal("0")
    for product_id, quantity in quantities.items():
        product = products[product_id]
        if product.stock < quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for '{product.name}'")
        total += product.price * quantity

    # 4. order and line items in a single transaction
    order = Order(user_id=current_user.id, status="new", total_amount=total)
    session.add(order)
    await session.flush()                      # getting order.id

    order_id = order.id
    created_at = order.created_at
    items_read = []
    for product_id, quantity in quantities.items():
        unit_price = products[product_id].price
        session.add(
            OrderItem(
                order_id=order_id,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
            )
        )
        items_read.append(
            OrderItemRead(product_id=product_id, quantity=quantity, unit_price=unit_price)
        )

    await session.commit()

    try:
        await broker.publish("order.created", {"order_id": order_id})
    except Exception:
        logger.exception("Failed to publish order.created for order %s", order_id)

    # The response is constructed from local variables; we do not touch ORM objects after a commit.
    return OrderRead(
        id=order_id,
        status="new",
        total_amount=total,
        created_at=created_at,
        items=items_read,
    )


@router.get("/orders", response_model=list[OrderSummary])
async def list_my_orders(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(Order)
        .where(Order.user_id == current_user.id)
        .order_by(Order.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # The user_id condition in the query ensures that an order belonging to someone else simply "won't be found."
    result = await session.execute(
        select(Order).where(Order.id == order_id, Order.user_id == current_user.id)
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    result = await session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
    )
    items = result.scalars().all()

    return OrderRead(
        id=order.id,
        status=order.status,
        total_amount=order.total_amount,
        created_at=order.created_at,
        items=[OrderItemRead.model_validate(i) for i in items],
    )