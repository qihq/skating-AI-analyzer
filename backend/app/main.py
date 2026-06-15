from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import ensure_storage_dirs, init_db
from app.routers.debug import router as debug_router
from app.routers.analysis import frames_router, plan_router, router as analysis_router
from app.routers.auth import router as auth_router
from app.routers.providers import router as providers_router
from app.routers.settings import router as settings_router
from app.routers.skaters import admin_router, router as skaters_router, session_router, system_router
from app.routers.snowball import router as snowball_router
from app.schemas import HealthResponse
from app.services.archive_policy import run_archive_policy
from app.services.pose import log_pose_runtime_mode
from app.services.skaters import seed_preset_skaters
from app.services.skills import seed_skill_catalog, sync_all_skater_progress
from app.services.snowball import seed_default_memories


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)


async def _sync_skater_progress_background() -> None:
    try:
        await sync_all_skater_progress()
    except Exception:  # noqa: BLE001
        logger.exception("Startup background skater progress sync failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("startup: ensure storage dirs")
    ensure_storage_dirs()
    logger.info("startup: log pose runtime")
    log_pose_runtime_mode()
    logger.info("startup: init db")
    await init_db()
    logger.info("startup: seed preset skaters")
    await seed_preset_skaters()
    logger.info("startup: seed default memories")
    await seed_default_memories()
    logger.info("startup: seed skill catalog")
    await seed_skill_catalog()
    sync_progress_mode = os.getenv("SYNC_SKATER_PROGRESS_ON_STARTUP", "0").strip().lower()
    if sync_progress_mode in {"1", "true", "yes"}:
        logger.info("startup: sync all skater progress")
        await sync_all_skater_progress()
    elif sync_progress_mode in {"background", "bg"}:
        logger.info("startup: schedule background skater progress sync")
        asyncio.create_task(_sync_skater_progress_background())
    else:
        logger.info("startup: skip skater progress sync")
    scheduler.add_job(run_archive_policy, "interval", hours=24, id="archive_policy", replace_existing=True)
    scheduler.start()
    logger.info("startup: complete")
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
app.include_router(debug_router)
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
