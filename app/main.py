from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.database.connection import init_db
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.shots import router as shots_router
from app.api.assets import router as assets_router
from app.api.scenes import router as scenes_router
from app.api.dashboard import router as dashboard_router
from app.api.issues import router as issues_router
from app.api.generation import router as generation_router
from app.api.approvals import router as approvals_router
from app.api.jobs import router as jobs_router
from app.core.config import settings
from app.core.version import APP_VERSION

BASE_DIR = Path(__file__).resolve().parent
settings.generated_media_path.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="AI Film OS",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(projects_router)
app.include_router(dashboard_router)
app.include_router(shots_router)
app.include_router(assets_router)
app.include_router(scenes_router)
app.include_router(issues_router)
app.include_router(generation_router)
app.include_router(approvals_router)
app.include_router(jobs_router)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/generated", StaticFiles(directory=settings.generated_media_path), name="generated")

@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")

@app.get("/script-import", response_class=HTMLResponse)
def script_import():
    return (BASE_DIR / "templates" / "script_import.html").read_text(encoding="utf-8")
