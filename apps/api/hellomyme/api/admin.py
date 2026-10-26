"""Team dashboard: members whose account id is in HELLOMYME_ADMIN_ACCOUNT_IDS see the numbers and
the review queue (members' own review texts, to approve or hide; no name or account is shown)."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from hellomyme.api.deps import Account, AppSettings, Conn
from hellomyme.domain import admin_stats, review
from hellomyme.domain.interview import InterviewError

router = APIRouter(prefix="/admin", tags=["admin"])


def _admin(settings, account_id: str, response: Response) -> None:
    if account_id not in settings.admin_account_ids:
        # The member's own id, so they can ask to be added; nothing else is told.
        raise HTTPException(403, {"message": "not an admin account", "account_id": account_id})
    response.headers["Cache-Control"] = "no-store"


@router.get("/stats")
def stats(conn: Conn, settings: AppSettings, account_id: Account, response: Response,
          range: admin_stats.Range = "7d", with_team: bool = False):  # noqa: A002
    _admin(settings, account_id, response)
    return admin_stats.stats(conn, range, with_team)


@router.get("/reviews")
def reviews(conn: Conn, settings: AppSettings, account_id: Account, response: Response):
    _admin(settings, account_id, response)
    return review.for_review(conn)


class DecisionRequest(BaseModel):
    decision: Literal["APPROVED", "HIDDEN"]


@router.post("/reviews/{review_id}")
def decide(review_id: UUID, body: DecisionRequest, conn: Conn, settings: AppSettings,
           account_id: Account, response: Response):
    _admin(settings, account_id, response)
    try:
        return review.decide(conn, str(review_id), body.decision, account_id)
    except InterviewError as exc:
        raise HTTPException(exc.status, {"message": exc.message}) from exc
