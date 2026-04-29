from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import ensure_storage_dirs, init_db
from app.routers.analysis import frames_router, plan_router, router as analysis_router
from app.routers.auth import router as auth_router
from app.routers.providers import router as providers_router
from app.routers.settings import router as settings_router
from app.routers.skaters import admin_router, router as skaters_router, session_router, system_router
from app.routers.snowball import router as snowball_router
from app.schemas import HealthResponse
from app.services.archive_policy import run_archive_policy
from app.services.pose import log_pose_runtime_mode
from app.services.providers import seed_preset_providers
from app.services.skaters import seed_preset_skaters
from app.services.skills import seed_skill_catalog, sync_all_skater_progress
from app.services.snowball import seed_default_memories


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_storage_dirs()
    log_pose_runtime_mode()
    await init_db()
    await seed_preset_providers()
    await seed_preset_skaters()
    await seed_default_memories()
    await seed_skill_catalog()
    await sync_all_skater_progress()
    scheduler.add_job(run_archive_policy, "interval", hours=24, id="archive_policy", replace_existing=True)
    scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Skating Analyzer",
    description="Skating training analysis system Phase 5",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis_router)
app.include_router(plan_router)
app.include_router(frames_router)
app.include_router(auth_router)
app.include_router(providers_router)
app.include_router(settings_router)
app.include_router(skaters_router)
app.include_router(session_router)
app.include_router(system_router)
app.include_router(admin_router)
app.include_router(snowball_router)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
