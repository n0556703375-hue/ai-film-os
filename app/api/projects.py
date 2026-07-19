from fastapi import APIRouter, HTTPException
from app.models.schemas import ProjectCreate, ProjectUpdate
from app.repositories import projects as repo

router = APIRouter(prefix="/api/projects", tags=["projects"])

@router.get("")
def list_projects():
    return repo.list_projects()

@router.post("")
def create_project(project: ProjectCreate):
    return repo.create_project(project.model_dump())

@router.get("/{project_id}")
def get_project(project_id: int):
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(404, "הפרויקט לא נמצא.")
    return project

@router.patch("/{project_id}")
def update_project(project_id: int, update: ProjectUpdate):
    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "לא התקבלו שדות לעדכון.")
    project = repo.update_project(project_id, fields)
    if not project:
        raise HTTPException(404, "הפרויקט לא נמצא.")
    return project
