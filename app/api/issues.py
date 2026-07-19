from fastapi import APIRouter, HTTPException
from app.repositories import issues as repo

router = APIRouter(prefix="/api/issues", tags=["issues"])

@router.get("")
def list_issues(resolved: bool | None = None):
    return repo.list_issues(resolved)

@router.patch("/{issue_id}/resolve")
def resolve_issue(issue_id: int, resolved: bool = True):
    if not repo.resolve_issue(issue_id, resolved):
        raise HTTPException(404, "הבעיה לא נמצאה.")
    return {"updated": True, "resolved": resolved}

@router.delete("/resolved")
def clear_resolved():
    return {"deleted": repo.clear_resolved()}
