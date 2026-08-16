import asyncio

import pytest

from tests.conftest import make_comment_event, sign


async def _post_signed(client, body):
    raw, sig = sign(body)
    return await client.post("/webhook", content=raw, headers={"X-PseudoGram-Signature": sig, "Content-Type": "application/json"})


@pytest.mark.asyncio
async def test_webhook_returns_200_fast(client):
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "list"})
    event = make_comment_event("evt_1", "What is the PRICE please?")
    resp = await _post_signed(client, event)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invalid_signature_rejected(client):
    event = make_comment_event("evt_bad_sig", "PRICE")
    import json
    resp = await client.post(
        "/webhook",
        content=json.dumps(event).encode(),
        headers={"X-PseudoGram-Signature": "sha256=deadbeef", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_signature_rejected(client):
    event = make_comment_event("evt_no_sig", "PRICE")
    resp = await client.post("/webhook", json=event)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_case_insensitive_and_substring_match_creates_job(client, db):
    await client.post("/rules", json={"keyword": "price", "dm_message": "list"})
    event = make_comment_event("evt_2", "Can I get the PrIcE please?")
    resp = await _post_signed(client, event)
    assert resp.status_code == 200
    job = await db.dm_jobs.find_one({"user_id": "usr_1"})
    assert job is not None
    assert job["status"] == "queued"


@pytest.mark.asyncio
async def test_no_match_creates_no_job(client, db):
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "list"})
    event = make_comment_event("evt_3", "just saying hi")
    await _post_signed(client, event)
    job = await db.dm_jobs.find_one({"user_id": "usr_1"})
    assert job is None


@pytest.mark.asyncio
async def test_multiple_matching_rules_creates_multiple_jobs(client, db):
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "list"})
    await client.post("/rules", json={"keyword": "INFO", "dm_message": "info"})
    event = make_comment_event("evt_4", "PRICE and INFO please")
    await _post_signed(client, event)
    count = await db.dm_jobs.count_documents({"user_id": "usr_1"})
    assert count == 2


@pytest.mark.asyncio
async def test_duplicate_event_id_is_ignored(client, db):
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "list"})
    event = make_comment_event("evt_dup", "PRICE")
    r1 = await _post_signed(client, event)
    r2 = await _post_signed(client, event)  # exact redelivery, same event_id
    assert r1.status_code == 200 and r2.status_code == 200
    count = await db.dm_jobs.count_documents({"user_id": "usr_1"})
    assert count == 1
    dup_count = await db.duplicates_log.count_documents({"reason": "duplicate_event_id"})
    assert dup_count == 1


@pytest.mark.asyncio
async def test_same_user_two_different_comments_same_rule_deduped(client, db):
    """Different event_id / comment_id, same user, same rule -> exactly one job."""
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "list"})
    e1 = make_comment_event("evt_5a", "PRICE", user_id="usr_2", comment_id="cmt_a")
    e2 = make_comment_event("evt_5b", "price please", user_id="usr_2", comment_id="cmt_b")
    await _post_signed(client, e1)
    await _post_signed(client, e2)
    count = await db.dm_jobs.count_documents({"user_id": "usr_2"})
    assert count == 1
    dup_count = await db.duplicates_log.count_documents({"reason": "duplicate_rule_user"})
    assert dup_count == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_comments_still_dedupe(client, db):
    """Simulates the race: many identical-user/rule events fired concurrently."""
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "list"})
    events = [
        make_comment_event(f"evt_race_{i}", "PRICE", user_id="usr_race", comment_id=f"cmt_race_{i}")
        for i in range(10)
    ]
    await asyncio.gather(*[_post_signed(client, e) for e in events])
    count = await db.dm_jobs.count_documents({"user_id": "usr_race"})
    assert count == 1


@pytest.mark.asyncio
async def test_comment_deleted_before_created_prevents_job(client, db):
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "list"})
    delete_event = make_comment_event(
        "evt_del", None, user_id="usr_3", comment_id="cmt_del", event_type="comment.deleted"
    )
    create_event = make_comment_event("evt_create_after_del", "PRICE", user_id="usr_3", comment_id="cmt_del")
    await _post_signed(client, delete_event)
    await _post_signed(client, create_event)
    job = await db.dm_jobs.find_one({"user_id": "usr_3"})
    assert job is None
