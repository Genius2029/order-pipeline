from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlmodel import SQLModel, Field


class TelegramLinkCode(SQLModel, table=True):
    code: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))