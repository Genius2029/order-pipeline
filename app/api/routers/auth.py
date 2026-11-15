import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.models.telegram_link_code import TelegramLinkCode


from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_session
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserRead

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=201)
async def register(data: UserCreate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == data.email))
    if result.scalars().first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login")
async def login(data: UserLogin, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == data.email))
    user = result.scalars().first()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


LINK_TTL_MINUTES = 15

@router.post("/me/telegram-link")
async def create_telegram_link(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    user_id = current_user.id      # remember the user ID before the session is closed

    # This user's old unused codes are no longer needed
    await session.execute(delete(TelegramLinkCode).where(TelegramLinkCode.user_id == user_id))

    code = secrets.token_urlsafe(16)
    session.add(
        TelegramLinkCode(
            code=code,
            user_id=user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=LINK_TTL_MINUTES),
        )
    )
    await session.commit()

    bot_username = os.getenv("BOT_USERNAME")
    return {
        "link": f"https://t.me/{bot_username}?start={code}",
        "expires_in_minutes": LINK_TTL_MINUTES,
    }