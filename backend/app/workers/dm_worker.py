"""
The background worker is the only thing that ever talks to
POST /v1/dm/send. The webhook handler never calls it directly -- it
only ever writes a `dm_jobs` document with status "queued" and returns.
That split is what keeps /webhook fast under a 500-event burst.

Job lifecycle (status field on a dm_jobs document):

    queued -> sending -> in_flight -> delivered   (happy path)
                       -> queued (retry, 429/500, attempts < max)
                       -> failed (400, or retries exhausted)
    in_flight -> delivered / failed  (via reconciliation poll)

Concurrency safety: a job is "claimed" via find_one_and_update, which
Mongo executes atomically server-side. Two worker loops (or two Render
instances, if that ever happens) racing for the same document will
never both get a "sending" result back -- one gets the document, the
other gets None and moves on. This is the same mechanism (atomic,
server-side, single document) as the duplicate-DM unique index; it's
just applied to "who owns this job right now" instead of "does this
job exist at all".
"""
import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import get_settings
from app.services.pseudogram_client import PseudoGramClient

RECONCILE_DELAY_SECONDS = 3  # give PseudoGram a moment before polling status


def _backoff_seconds(attempts: int) -> float:
    base = min(60, 2 ** attempts)
    return base + random.uniform(0, base * 0.25)


async def _claim_one_queued(db: AsyncIOMotorDatabase) -> dict | None:
    now = datetime.now(timezone.utc)
    return await db.dm_jobs.find_one_and_update(
        {
            "status": "queued",
            "$or": [{"next_retry_at": None}, {"next_retry_at": {"$lte": now}}],
        },
        {"$set": {"status": "sending", "updated_at": now}},
    )


async def _claim_one_in_flight(db: AsyncIOMotorDatabase) -> dict | None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=RECONCILE_DELAY_SECONDS)
    return await db.dm_jobs.find_one_and_update(
        {"status": "in_flight", "last_checked_at": {"$lte": cutoff}},
        {"$set": {"status": "reconciling", "updated_at": datetime.now(timezone.utc)}},
    )


async def _process_send(db: AsyncIOMotorDatabase, job: dict, client: PseudoGramClient) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    job_id = str(job["_id"])
    attempts = job.get("attempts", 0)

    # Comment-deletion handling (Part C): if a comment.deleted tombstone
    # exists for this comment and we have not yet sent anything, we
    # choose NOT to send. Rationale: the commenter retracted the action
    # that triggered the DM. Documented as a judgment call in FAILURES.md.
    comment = await db.comments.find_one({"comment_id": job["comment_id"]})
    if comment and comment.get("deleted"):
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "failed", "error": "comment_deleted_before_send", "updated_at": now}},
        )
        return

    idempotency_key = f"job-{job_id}"
    try:
        resp = await client.send_dm(
            recipient_user_id=job["user_id"],
            message=job["dm_message"],
            comment_id=job["comment_id"],
            idempotency_key=idempotency_key,
        )
    except Exception as exc:  # network error, timeout, etc -- treat as retryable
        await _retry_or_fail(db, job, attempts, str(exc))
        return

    if resp.status_code == 202:
        body = resp.json()
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": "in_flight",
                    "dm_id": body["dm_id"],
                    "attempts": attempts + 1,
                    "last_checked_at": now,
                    "updated_at": now,
                }
            },
        )
        return

    if resp.status_code == 429:
        retry_after = float(resp.headers.get("Retry-After", 5))
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": "queued",
                    "next_retry_at": now + timedelta(seconds=retry_after),
                    "attempts": attempts + 1,
                    "updated_at": now,
                }
            },
        )
        return

    if resp.status_code == 400:
        detail = resp.text
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "failed", "error": f"invalid_request: {detail}", "updated_at": now}},
        )
        return

    # 500 or anything else unexpected -> retryable
    await _retry_or_fail(db, job, attempts, f"http_{resp.status_code}")


async def _retry_or_fail(db: AsyncIOMotorDatabase, job: dict, attempts: int, error: str) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    new_attempts = attempts + 1
    if new_attempts >= settings.dm_max_attempts:
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "failed", "error": error, "attempts": new_attempts, "updated_at": now}},
        )
        return
    await db.dm_jobs.update_one(
        {"_id": job["_id"]},
        {
            "$set": {
                "status": "queued",
                "next_retry_at": now + timedelta(seconds=_backoff_seconds(new_attempts)),
                "attempts": new_attempts,
                "error": error,
                "updated_at": now,
            }
        },
    )


async def _process_reconcile(db: AsyncIOMotorDatabase, job: dict, client: PseudoGramClient) -> None:
    now = datetime.now(timezone.utc)
    try:
        resp = await client.get_dm_status(job["dm_id"])
    except Exception:
        # transient read failure -- go back to in_flight, try again later
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "in_flight", "last_checked_at": now, "updated_at": now}},
        )
        return

    if resp.status_code != 200:
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "in_flight", "last_checked_at": now, "updated_at": now}},
        )
        return

    remote_status = resp.json().get("status")
    if remote_status == "delivered":
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "delivered", "updated_at": now}},
        )
    elif remote_status == "failed":
        # PseudoGram accepted it, then it actually failed. Retry the
        # send (bounded) rather than giving up immediately.
        await _retry_or_fail(db, job, job.get("attempts", 0), "dm_delivery_failed")
    else:  # still "queued" on their side -- check again later
        await db.dm_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "in_flight", "last_checked_at": now, "updated_at": now}},
        )


async def run_worker_loop(db: AsyncIOMotorDatabase, stop_event: asyncio.Event) -> None:
    settings = get_settings()
    client = PseudoGramClient()
    while not stop_event.is_set():
        did_work = False

        job = await _claim_one_queued(db)
        if job:
            did_work = True
            await _process_send(db, job, client)

        job = await _claim_one_in_flight(db)
        if job:
            did_work = True
            await _process_reconcile(db, job, client)

        if not did_work:
            await asyncio.sleep(settings.dm_worker_poll_seconds)
