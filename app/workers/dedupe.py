from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select

from app.models.processed_message import ProcessedMessage


async def mark_processed(session, consumer: str, message_id: str) -> bool:
    """Records "message processed." True means the record is new, False means it's already been processed."""
    result = await session.execute(
        insert(ProcessedMessage)
        .values(consumer=consumer, message_id=message_id)
        .on_conflict_do_nothing()
        .returning(ProcessedMessage.message_id)
    )
    return result.scalar_one_or_none() is not None


async def was_processed(session, consumer: str, message_id: str) -> bool:
    result = await session.execute(
        select(ProcessedMessage.message_id).where(
            ProcessedMessage.consumer == consumer,
            ProcessedMessage.message_id == message_id,
        )
    )
    return result.scalar_one_or_none() is not None