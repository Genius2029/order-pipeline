from decimal import Decimal

from sqlalchemy import Column, Numeric
from sqlmodel import SQLModel, Field


class OrderItem(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    quantity: int
    unit_price: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))