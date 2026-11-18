from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, func
from sqlmodel import SQLModel, Field


class ProcessedMessage(SQLModel, table=True):
    consumer: str = Field(primary_key=True)
    message_id: str = Field(primary_key=True)
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )