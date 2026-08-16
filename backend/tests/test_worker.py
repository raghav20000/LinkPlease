from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.services.pseudogram_client import PseudoGramClient, dm_send_rate_limiter
from app.workers import dm_worker

BASE = "https://pseudogram-api.onrender.com"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    dm_send_rate_limiter._timestamps.clear()
    yield
    dm_send_rate_limiter._timestamps.clear()


def _job(**overrides):
    base = {
        "rule_id": "r1",
        "user_id": "u1",
        "comment_id": "c1",
        "dm_message": "hi",
        "status": "sending",
        "attempts": 0,
        "next_retry_at": None,
        "dm_id": None,
        "error": None,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
@respx.mock
async def test_202_moves_job_to_in_flight(db):
    respx.post(f"{BASE}/v1/dm/send").mock(
        return_value=httpx.Response(202, json={"dm_id": "dm_1", "status": "queued"})
    )
    job = _job()
    result = await db.dm_jobs.insert_one(job)
    job["_id"] = result.inserted_id

    await dm_worker._process_send(db, job, PseudoGramClient())

    updated = await db.dm_jobs.find_one({"_id": job["_id"]})
    assert updated["status"] == "in_flight"
    assert updated["dm_id"] == "dm_1"


@pytest.mark.asyncio
@respx.mock
async def test_429_requeues_with_retry_after(db):
    respx.post(f"{BASE}/v1/dm/send").mock(
        return_value=httpx.Response(429, json={"error": "rate_limited"}, headers={"Retry-After": "7"})
    )
    job = _job()
    result = await db.dm_jobs.insert_one(job)
    job["_id"] = result.inserted_id

    await dm_worker._process_send(db, job, PseudoGramClient())

    updated = await db.dm_jobs.find_one({"_id": job["_id"]})
    assert updated["status"] == "queued"
    assert updated["next_retry_at"] is not None
    assert updated["attempts"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_400_fails_immediately_no_retry(db):
    respx.post(f"{BASE}/v1/dm/send").mock(
        return_value=httpx.Response(400, json={"error": "invalid_request", "detail": "bad"})
    )
    job = _job()
    result = await db.dm_jobs.insert_one(job)
    job["_id"] = result.inserted_id

    await dm_worker._process_send(db, job, PseudoGramClient())

    updated = await db.dm_jobs.find_one({"_id": job["_id"]})
    assert updated["status"] == "failed"
    assert updated["attempts"] == 0  # never retried, so attempts count didn't increment


@pytest.mark.asyncio
@respx.mock
async def test_500_retries_until_max_attempts_then_fails(db, monkeypatch):
    monkeypatch.setenv("DM_MAX_ATTEMPTS", "2")
    from app.config import get_settings
    get_settings.cache_clear()

    respx.post(f"{BASE}/v1/dm/send").mock(return_value=httpx.Response(500, json={"error": "internal_error"}))
    job = _job(attempts=1)  # already tried once
    result = await db.dm_jobs.insert_one(job)
    job["_id"] = result.inserted_id

    await dm_worker._process_send(db, job, PseudoGramClient())

    updated = await db.dm_jobs.find_one({"_id": job["_id"]})
    assert updated["status"] == "failed"
    assert updated["attempts"] == 2
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_reconcile_delivered_marks_job_delivered(db):
    respx.get(f"{BASE}/v1/dm/dm_1").mock(
        return_value=httpx.Response(200, json={"dm_id": "dm_1", "status": "delivered", "recipient_user_id": "u1"})
    )
    job = _job(status="reconciling", dm_id="dm_1")
    result = await db.dm_jobs.insert_one(job)
    job["_id"] = result.inserted_id

    await dm_worker._process_reconcile(db, job, PseudoGramClient())

    updated = await db.dm_jobs.find_one({"_id": job["_id"]})
    assert updated["status"] == "delivered"


@pytest.mark.asyncio
@respx.mock
async def test_comment_deleted_before_send_skips_dm(db):
    await db.comments.insert_one({"comment_id": "c1", "deleted": True})
    route = respx.post(f"{BASE}/v1/dm/send")
    job = _job()
    result = await db.dm_jobs.insert_one(job)
    job["_id"] = result.inserted_id

    await dm_worker._process_send(db, job, PseudoGramClient())

    updated = await db.dm_jobs.find_one({"_id": job["_id"]})
    assert updated["status"] == "failed"
    assert updated["error"] == "comment_deleted_before_send"
    assert not route.called
