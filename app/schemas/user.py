from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=8)


class UserLogin(BaseModel):
    email: str
    password: str


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    is_admin: bool