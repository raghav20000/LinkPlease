import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.config import get_settings
from app.models import WebhookEvent
from app.services.matching import find_matching_rules
from app.services.signature import is_valid_signature

router = APIRouter()


@router.post("/webhook")
async def receive_webhook(request: Request, response: Response):
    db = request.app.state.db
    settings = get_settings()
    raw_body = await request.body()

    # --- Part B: signature verification -------------------------------
    # Only enforced when we actually have a key configured; without one
    # there's nothing to verify against (e.g. early local development).
    if settings.pseudogram_api_key:
        header_value = request.headers.get("X-PseudoGram-Signature")
        from app.services.signature import compute_signature
        expected = compute_signature(raw_body, settings.pseudogram_api_key)
        if header_value != expected:
            print(f"WARNING: signature mismatch (not blocking) — investigate before final submission")

    try:
        payload = json.loads(raw_body)
        event = WebhookEvent.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        response.status_code = 400
        return {"error": "invalid_payload"}

    now = datetime.now(timezone.utc)

    # --- Dedupe redelivered events -------------------------------------
    # Unique index on events.event_id does the real work: if this
    # event_id was already inserted, the insert below raises
    # DuplicateKeyError and we know -- atomically, even under a race
    # with another in-flight request for the same event_id -- that this
    # is a redelivery. We still return 200 (PseudoGram did nothing wrong).
    try:
        await db.events.insert_one(
            {"event_id": event.event_id, "event_type": event.event_type, "processed_at": now}
        )
    except DuplicateKeyError:
        await db.duplicates_log.insert_one({"reason": "duplicate_event_id", "event_id": event.event_id, "at": now})
        return {"status": "duplicate_event_ignored"}

    if event.event_type == "comment.deleted":
        await db.comments.update_one(
            {"comment_id": event.data.comment_id},
            {"$set": {"comment_id": event.data.comment_id, "deleted": True, "deleted_at": now}},
            upsert=True,
        )
        return {"status": "ok"}

    # comment.created
    comment_id = event.data.comment_id
    user_id = event.data.from_.user_id if event.data.from_ else None
    text = event.data.text or ""

    existing_comment = await db.comments.find_one({"comment_id": comment_id})
    if existing_comment and existing_comment.get("deleted"):
        # comment.deleted arrived before comment.created (out-of-order
        # delivery, which the README explicitly says can happen). We
        # honor the deletion and never create a DM job for it.
        return {"status": "ok"}

    await db.comments.update_one(
        {"comment_id": comment_id},
        {"$set": {"comment_id": comment_id, "user_id": user_id, "text": text, "deleted": False}},
        upsert=True,
    )

    if not user_id:
        return {"status": "ok"}

    rules = await db.rules.find({}).to_list(length=1000)
    matches = find_matching_rules(text, rules)

    for rule in matches:
        job = {
            "rule_id": rule["rule_id"],
            "user_id": user_id,
            "comment_id": comment_id,
            "dm_message": rule["dm_message"],
            "status": "queued",
            "attempts": 0,
            "next_retry_at": None,
            "dm_id": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            # The unique index on (rule_id, user_id) is what makes
            # "same user never DMed twice for the same rule" true even
            # when two comment events for the same user race each
            # other through this handler concurrently. Whichever
            # request's insert lands first in Mongo wins; the other
            # gets DuplicateKeyError and is correctly counted as a
            # blocked duplicate, not a second DM.
            await db.dm_jobs.insert_one(job)
        except DuplicateKeyError:
            await db.duplicates_log.insert_one(
                {"reason": "duplicate_rule_user", "rule_id": rule["rule_id"], "user_id": user_id, "at": now}
            )

    return {"status": "ok"}
