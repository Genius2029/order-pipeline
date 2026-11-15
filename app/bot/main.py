import asyncio
import logging
import os
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message as TgMessage
from dotenv import load_dotenv
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine
from app.models.telegram_link_code import TelegramLinkCode
from app.models.user import User

load_dotenv()
logging.basicConfig(level=logging.INFO)

router = Router()


async def consume_link_code(code: str, chat_id: int, db_engine=engine) -> bool:
    """It atomically "consumes" a one-time code and links the chat to the user."""
    async with AsyncSession(db_engine) as session:
        result = await session.execute(
            delete(TelegramLinkCode)
            .where(
                TelegramLinkCode.code == code,
                TelegramLinkCode.expires_at > datetime.now(timezone.utc),
            )
            .returning(TelegramLinkCode.user_id)
        )
        user_id = result.scalar_one_or_none()

        if user_id is not None:
            # One chat belongs to one account.
            await session.execute(
                update(User).where(User.telegram_chat_id == chat_id).values(telegram_chat_id=None)
            )
            await session.execute(
                update(User).where(User.id == user_id).values(telegram_chat_id=chat_id)
            )
        await session.commit()

    return user_id is not None


@router.message(CommandStart(deep_link=True))
async def start_with_code(message: TgMessage, command: CommandObject):
    if await consume_link_code(command.args, message.chat.id):
        await message.answer("Account linked. You will receive notifications about orders here.")
    else:
        await message.answer("The link is invalid or has expired. Please create a new one.")


@router.message(CommandStart())
async def start_plain(message: TgMessage):
    await message.answer(
        "Hello! To receive notifications about orders, please link your account via the link from your personal account."
    )


async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass