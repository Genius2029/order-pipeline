import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field


class OutboxEvent(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), unique=True)
    routing_key: str
    payload: dict = Field(sa_column=Column(JSONB, nullable=False))
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )
    published_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )