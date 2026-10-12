"""Team dashboard: members whose account id is in HELLOMYME_ADMIN_ACCOUNT_IDS see the numbers."""
from fastapi import APIRouter, HTTPException, Response

from hellomyme.api.deps import Account, AppSettings, Conn
from hellomyme.domain import admin_stats

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
def stats(conn: Conn, settings: AppSettings, account_id: Account, response: Response,
          range: admin_stats.Range = "7d", with_team: bool = False):  # noqa: A002
    if account_id not in settings.admin_account_ids:
        # The member's own id, so they can ask to be added; nothing else is told.
        raise HTTPException(403, {"message": "not an admin account", "account_id": account_id})
    response.headers["Cache-Control"] = "no-store"
    return admin_stats.stats(conn, range, with_team)
