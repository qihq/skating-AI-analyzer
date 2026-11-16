"""Fail-closed gates for the isolated NAS trial; unset leaves normal installs unchanged."""
from __future__ import annotations
import os
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Match


def trial_profile() -> str:
    sealed = Path("/etc/skating-trial-profile")
    baked = sealed.read_text().strip() if sealed.is_file() else None
    value = os.getenv("SKATING_TRIAL_PROFILE", baked or "off")
    if baked and value != baked:
        raise RuntimeError("Trial image profile is fixed; build another image to change it")
    if value not in {"off", "web-preview", "legacy-analysis-preview"}:
        raise RuntimeError("Invalid SKATING_TRIAL_PROFILE")
    return value


def trial_capabilities() -> dict:
    profile = trial_profile()
    return {"profile": profile, "version": os.getenv("SKATING_TRIAL_VERSION", "development"),
            "video_analysis": profile == "legacy-analysis-preview", "new_diagnostics": False,
            "external_ai": False, "target_nas_verified": False,
            "limitation": "隔离试用；新诊断、shadow、受控评估及外部 AI 均关闭。" +
            ("本版不能上传或分析视频。" if profile == "web-preview" else "仅既有 legacy 本地分析；未验证真人准确率，未配置 AI 报告供应商。")}


def external_ai_allowed() -> bool:
    return trial_profile() == "off"


def require_external_ai() -> None:
    if not external_ai_allowed():
        raise RuntimeError("external_ai_disabled: 本地试用版禁止外部 AI 请求")


class TrialGate:
    def __init__(self, app, routes):
        self.app, self.routes = app, routes
        self.analysis_busy = False

    async def __call__(self, scope, receive, send):
        profile = trial_profile()
        if scope["type"] != "http" or profile == "off":
            return await self.app(scope, receive, send)
        endpoint = None
        for route in self.routes:
            match, child = route.matches(scope)
            if match == Match.FULL:
                endpoint = child.get("endpoint")
                break
        module = getattr(endpoint, "__module__", "")
        name = getattr(endpoint, "__name__", "")
        method = scope["method"]
        read = method in {"GET", "HEAD", "OPTIONS"}
        forbidden = (module == "app.routers.settings" and name == "test_api_connection") or module in {"app.routers.shadow", "app.routers.debug", "app.routers.golden_v2"}
        if module == "app.routers.analysis_v2":
            forbidden = name != "get_analysis_experience_v2"
        analysis_write = module == "app.routers.analysis" and not read
        local_analysis = analysis_write and name in {"upload_analysis", "retry_analysis", "confirm_target_lock"}
        allowed_write = module in {"app.routers.auth", "app.routers.skaters"} and name not in {"restore_backup", "create_backup"}
        # Admin endpoints, settings/providers, report/comparison/AI routes fail closed.
        if scope["path"].startswith("/api/admin"):
            forbidden = True
        allowed = not forbidden and (read or allowed_write or (profile == "legacy-analysis-preview" and local_analysis))
        if not allowed:
            return await JSONResponse({"detail": trial_capabilities()["limitation"], "code": "trial_feature_disabled"}, status_code=403)(scope, receive, send)
        if local_analysis:
            if self.analysis_busy:
                return await JSONResponse({"detail": "试用版一次只处理一个视频，请稍后重试。"}, status_code=429)(scope, receive, send)
            from app.services.local_runtime import require_local_runtime
            from fastapi import HTTPException
            try:
                require_local_runtime()
            except HTTPException as exc:
                return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            self.analysis_busy = True
            try:
                return await self.app(scope, receive, send)
            finally:
                self.analysis_busy = False
        await self.app(scope, receive, send)
