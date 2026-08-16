"""
Mongo connection and index setup.

The unique indexes here are load-bearing, not decorative: they are the
actual mechanism that makes duplicate-event and duplicate-DM protection
race-safe. See services/matching.py and workers/dm_worker.py for how
they're used.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.mongodb_uri)
        _db = _client[settings.mongodb_db_name]
    return _db


def set_db(db: AsyncIOMotorDatabase) -> None:
    """Used by tests to inject a mongomock database."""
    global _db
    _db = db


async def ensure_indexes(db: AsyncIOMotorDatabase | None = None) -> None:
    if db is None:
        db = get_db()

    # Dedupes redelivered webhook events. This is what makes "same
    # event_id arrives twice" a no-op instead of a double-processed event.
    await db.events.create_index("event_id", unique=True)

    # The core duplicate-DM guard: one job per (rule_id, user_id), period.
    # Two concurrent webhook events for the same user+rule race to insert
    # this document; Mongo's unique index lets exactly one insert win and
    # rejects the other with a DuplicateKeyError, atomically, at the
    # storage layer -- not in Python memory.
    await db.dm_jobs.create_index([("rule_id", 1), ("user_id", 1)], unique=True)

    await db.dm_jobs.create_index("status")
    await db.dm_jobs.create_index("next_retry_at")
    await db.rules.create_index("rule_id", unique=True)
    await db.comments.create_index("comment_id", unique=True)
