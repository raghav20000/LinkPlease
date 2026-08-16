import asyncio
import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import get_settings
from app.database import ensure_indexes


TEST_API_KEY = "test-secret-key"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    monkeypatch.setenv("PSEUDOGRAM_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("DM_MAX_ATTEMPTS", "3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    database = client["test_db"]
    await ensure_indexes(database)
    return database


@pytest_asyncio.fixture
async def app(db):
    # Imported here so env vars from _settings_env are already applied
    from app.main import app as fastapi_app

    fastapi_app.state.db = db
    return fastapi_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def sign(body: dict) -> tuple[bytes, str]:
    raw = json.dumps(body).encode("utf-8")
    digest = hmac.new(TEST_API_KEY.encode(), raw, hashlib.sha256).hexdigest()
    return raw, f"sha256={digest}"


def make_comment_event(event_id, text, user_id="usr_1", comment_id="cmt_1", event_type="comment.created"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "sent_at": "2026-08-10T09:14:22.481Z",
        "data": {
            "comment_id": comment_id,
            "post_id": "post_1",
            "text": text,
            "created_at": "2026-08-10T09:14:21.900Z",
            "from": {"user_id": user_id, "username": "someone"},
        },
    }
