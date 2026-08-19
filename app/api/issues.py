from fastapi import APIRouter, HTTPException
from app.models.schemas import ContinuityIssueCreate, ContinuityIssueUpdate
from app.repositories import issues as repo
from app.services.continuity import continuity_preview
from app.services.shot_visual_continuity import visual_continuity_ai_issues

router = APIRouter(prefix="/api/issues", tags=["issues"])


@router.get("")
def list_issues(resolved: bool | None = None, project_id: int | None = None):
    return repo.list_issues(resolved, project_id)


@router.get("/shots/{shot_id}/continuity-preview")
def preview_shot_continuity(shot_id: int, include_ai: bool = True):
    preview = continuity_preview(shot_id)
    if not preview:
        raise HTTPException(404, "השוט לא נמצא.")
    if include_ai:
        ai_issues = visual_continuity_ai_issues(shot_id)
        if ai_issues:
            preview["issues"] = preview["issues"] + ai_issues
            preview["issue_count"] = len(preview["issues"])
            preview["blocking_issue_count"] = sum(
                1 for issue in preview["issues"] if issue["severity"] in {"critical", "high"}
            )
            preview["can_finalize"] = preview["blocking_issue_count"] == 0
    return preview


@router.post("")
def create_issue(issue: ContinuityIssueCreate):
    return repo.create_issue(issue.model_dump())


@router.patch("/{issue_id}")
def update_issue(issue_id: int, project_id: int, update: ContinuityIssueUpdate):
    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "לא התקבלו שדות לעדכון.")
    try:
        issue = repo.update_issue(issue_id, project_id, fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not issue:
        raise HTTPException(404, "הבעיה לא נמצאה בפרויקט שנבחר.")
    return issue


@router.patch("/{issue_id}/resolve")
def resolve_issue(issue_id: int, project_id: int, resolved: bool = True):
    try:
        updated = repo.resolve_issue(issue_id, project_id, resolved)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not updated:
        raise HTTPException(404, "הבעיה לא נמצאה בפרויקט שנבחר.")
    return {
        "updated": True,
        "resolved": resolved,
        "project_id": project_id,
    }


@router.delete("/resolved")
def clear_resolved(project_id: int):
    try:
        deleted = repo.clear_resolved(project_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"deleted": deleted, "project_id": project_id}
