from fastapi import APIRouter, Request

from app.models import StatsResponse

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
async def get_stats(request: Request):
    db = request.app.state.db

    # Every number here is a live count derived from persisted state --
    # nothing is a running counter that could drift from reality.
    sent = await db.dm_jobs.count_documents({"status": "delivered"})
    failed = await db.dm_jobs.count_documents({"status": "failed"})
    queued = await db.dm_jobs.count_documents(
        {"status": {"$in": ["queued", "sending", "in_flight", "reconciling"]}}
    )
    duplicates_blocked = await db.duplicates_log.count_documents({})

    return StatsResponse(sent=sent, failed=failed, queued=queued, duplicates_blocked=duplicates_blocked)
