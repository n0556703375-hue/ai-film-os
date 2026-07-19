from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.database.connection import init_db
from app.api.health import router as health_router
from app.api.shots import router as shots_router
from app.api.assets import router as assets_router
from app.api.scenes import router as scenes_router
from app.api.dashboard import router as dashboard_router
from app.api.issues import router as issues_router

BASE_DIR = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="AI Film OS",
    version="3.3.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(dashboard_router)
app.include_router(shots_router)
app.include_router(assets_router)
app.include_router(scenes_router)
app.include_router(issues_router)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
