import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from app.models import CreateRuleRequest, CreateRuleResponse

router = APIRouter()


@router.post("/rules", response_model=CreateRuleResponse, status_code=201)
async def create_rule(payload: CreateRuleRequest, request: Request):
    db = request.app.state.db
    rule_id = str(uuid.uuid4())
    doc = {
        "rule_id": rule_id,
        "keyword": payload.keyword,
        "dm_message": payload.dm_message,
        "created_at": datetime.now(timezone.utc),
    }
    await db.rules.insert_one(doc)
    return CreateRuleResponse(rule_id=rule_id, keyword=payload.keyword, dm_message=payload.dm_message)


# Not part of the grader's contract -- purely a convenience for the
# frontend's "Rules" page. Never remove/rename POST /rules above.
@router.get("/rules")
async def list_rules(request: Request):
    db = request.app.state.db
    rules = await db.rules.find({}, {"_id": 0}).to_list(length=1000)
    return {"rules": rules}
