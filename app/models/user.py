from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import BigInteger, Column

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    full_name: str 
    is_admin: bool = False
    telegram_chat_id: Optional[int] = Field(
    default=None,
    sa_column=Column(BigInteger, unique=True, index=True, nullable=True),
    )