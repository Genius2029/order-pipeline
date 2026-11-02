from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, Numeric
from sqlmodel import SQLModel, Field


class Order(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    status: str = Field(default="new", index=True)
    total_amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())