from typing import Literal, Optional
from pydantic import BaseModel, Field


class CreateRuleRequest(BaseModel):
    keyword: str
    dm_message: str


class CreateRuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str


class StatsResponse(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int


class WebhookCommentFrom(BaseModel):
    user_id: str
    username: str


class WebhookCommentData(BaseModel):
    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[str] = None
    from_: Optional[WebhookCommentFrom] = Field(default=None, alias="from")

    model_config = {"populate_by_name": True}


class WebhookEvent(BaseModel):
    event_id: str
    event_type: Literal["comment.created", "comment.deleted"]
    sent_at: Optional[str] = None
    data: WebhookCommentData
