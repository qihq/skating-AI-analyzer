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

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

from app.analysis_v2.config import apply_runtime_environment, load_runtime_config

runtime_config = load_runtime_config(os.environ, project_root=ROOT_DIR)
apply_runtime_environment(runtime_config, os.environ)

from app.database import AsyncSessionLocal, ensure_storage_dirs, init_db
from app.routers.capabilities import configure_runtime_capabilities, router as capabilities_router
from app.routers.golden_v2 import router as golden_v2_router
from app.routers.analysis_v2 import router as analysis_v2_router
from app.routers.shadow import router as shadow_router
from app.routers.debug import router as debug_router
from app.routers.analysis import frames_router, plan_router, router as analysis_router
from app.routers.auth import router as auth_router
from app.routers.growth import router as growth_router
from app.routers.annual import recover_incomplete_exports, router as annual_router, run_export
from app.routers.providers import router as providers_router
from app.routers.settings import router as settings_router
from app.routers.skaters import admin_router, router as skaters_router, session_router, system_router
from app.routers.snowball import router as snowball_router
from app.schemas import HealthResponse
from app.services.archive_policy import run_archive_policy
from app.services.analysis_corrections import backfill_applied_analysis_corrections
from app.services.annual_pdf import AnnualPdfFontError, validate_font_paths
from app.services.pose import log_pose_runtime_mode
from app.services.skaters import seed_preset_skaters
from app.services.skills import seed_skill_catalog, sync_all_skater_progress
from app.services.snowball import seed_default_memories


logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)
annual_export_tasks: set[asyncio.Task[None]] = set()


async def _sync_skater_progress_background() -> None:
    try:
        await sync_all_skater_progress()
    except Exception:  # noqa: BLE001
        logger.exception("Startup background skater progress sync failed")


async def _backfill_applied_corrections_startup() -> None:
    try:
        async with AsyncSessionLocal() as session:
            count = await backfill_applied_analysis_corrections(session)
        if count:
            logger.info("startup: backfilled %s analyses from applied corrections", count)
    except Exception:  # noqa: BLE001
        logger.exception("Startup applied correction backfill failed")


async def _recover_annual_exports_startup() -> None:
    async def enqueue(export_id: str) -> None:
        task = asyncio.create_task(run_export(export_id))
        annual_export_tasks.add(task)
        task.add_done_callback(annual_export_tasks.discard)

    try:
        recovered = await recover_incomplete_exports(enqueue=enqueue)
        if recovered:
            logger.info("startup: resumed %s interrupted annual exports", len(recovered))
    except Exception:  # noqa: BLE001
        logger.exception("Startup annual export recovery failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("startup: ensure storage dirs")
    ensure_storage_dirs()
    try:
        validate_font_paths()
    except AnnualPdfFontError as exc:
        logger.warning("startup: annual PDF fonts unavailable: %s", exc)
    logger.info("startup: log pose runtime")
    log_pose_runtime_mode()
    logger.info("startup: init db")
    await init_db()
    from app.services.local_runtime import recover_interrupted_local_analyses
    await recover_interrupted_local_analyses()
    logger.info("startup: backfill applied corrections")
    await _backfill_applied_corrections_startup()
    await _recover_annual_exports_startup()
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
    pending_export_tasks = tuple(annual_export_tasks)
    for task in pending_export_tasks:
        task.cancel()
    if pending_export_tasks:
        await asyncio.gather(*pending_export_tasks, return_exceptions=True)
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Skating Analyzer",
    description="Skating training analysis system Phase 5",
    version="0.5.1",
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
app.include_router(growth_router)
app.include_router(annual_router)
app.include_router(session_router)
app.include_router(system_router)
app.include_router(admin_router)
app.include_router(snowball_router)
configure_runtime_capabilities(runtime_config)
app.include_router(capabilities_router)
app.include_router(golden_v2_router)
app.include_router(analysis_v2_router)
app.include_router(shadow_router)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


# Trial gates run before routing/dependencies/body parsing and background task creation.
from app.trial import TrialGate, trial_capabilities, trial_profile

if trial_profile() != "off":
    if runtime_config.pipeline_mode.value != "legacy":
        raise RuntimeError("Trial requires SKATING_ANALYSIS_PIPELINE=legacy")
    app.add_middleware(TrialGate, routes=app.router.routes)

@app.get("/api/trial")
async def trial_status():
    return trial_capabilities()
