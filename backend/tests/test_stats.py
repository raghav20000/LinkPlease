import pytest


@pytest.mark.asyncio
async def test_stats_shape_and_zero_state(client):
    resp = await client.get("/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"sent", "failed", "queued", "duplicates_blocked"}
    assert body == {"sent": 0, "failed": 0, "queued": 0, "duplicates_blocked": 0}


@pytest.mark.asyncio
async def test_stats_reflect_persisted_job_statuses(client, db):
    await db.dm_jobs.insert_many(
        [
            {"rule_id": "r1", "user_id": "u1", "status": "delivered"},
            {"rule_id": "r1", "user_id": "u2", "status": "delivered"},
            {"rule_id": "r1", "user_id": "u3", "status": "failed"},
            {"rule_id": "r1", "user_id": "u4", "status": "queued"},
            {"rule_id": "r1", "user_id": "u5", "status": "in_flight"},
        ]
    )
    await db.duplicates_log.insert_many([{"reason": "duplicate_event_id"} for _ in range(3)])

    resp = await client.get("/stats")
    body = resp.json()
    assert body["sent"] == 2
    assert body["failed"] == 1
    assert body["queued"] == 2  # queued + in_flight
    assert body["duplicates_blocked"] == 3


@pytest.mark.asyncio
async def test_stats_does_not_count_attempts_as_sent(client, db):
    """A DM that was merely *accepted* (202/in_flight) is not 'sent' until delivered."""
    await db.dm_jobs.insert_one({"rule_id": "r1", "user_id": "u1", "status": "in_flight", "attempts": 3})
    resp = await client.get("/stats")
    assert resp.json()["sent"] == 0
    assert resp.json()["queued"] == 1
