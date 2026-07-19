from fastapi import APIRouter, HTTPException
from app.models.schemas import ContinuityIssueCreate, ContinuityIssueUpdate
from app.repositories import issues as repo

router = APIRouter(prefix="/api/issues", tags=["issues"])

@router.get("")
def list_issues(resolved: bool | None = None, project_id: int | None = None):
    return repo.list_issues(resolved, project_id)

@router.post("")
def create_issue(issue: ContinuityIssueCreate):
    return repo.create_issue(issue.model_dump())

@router.patch("/{issue_id}")
def update_issue(issue_id: int, update: ContinuityIssueUpdate):
    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "לא התקבלו שדות לעדכון.")
    issue = repo.update_issue(issue_id, fields)
    if not issue:
        raise HTTPException(404, "הבעיה לא נמצאה.")
    return issue

@router.patch("/{issue_id}/resolve")
def resolve_issue(issue_id: int, resolved: bool = True):
    if not repo.resolve_issue(issue_id, resolved):
        raise HTTPException(404, "הבעיה לא נמצאה.")
    return {"updated": True, "resolved": resolved}

@router.delete("/resolved")
def clear_resolved():
    return {"deleted": repo.clear_resolved()}
