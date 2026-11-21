"""FastAPI 앱의 시작점.

실행: (backend 폴더에서) uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import get_workspace
from app.api.routes import edits, files, health, jobs, separations
from app.core.config import APP_NAME, APP_VERSION
from app.jobs.manager import JobManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버가 켜질 때: 작업 폴더를 준비하고, 작업 관리자(작업자 1명)를 만든다
    ws = get_workspace()
    ws.ensure()
    app.state.job_manager = JobManager(ws.jobs, max_workers=1)
    yield
    # 서버가 꺼질 때: 대기 중인 작업은 취소하고 작업자 정리
    app.state.job_manager.shutdown(wait=False)


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

# 모든 API 주소 앞에 /api 를 붙인다 → /api/health, /api/files ...
app.include_router(health.router, prefix="/api", tags=["system"])
app.include_router(files.router, prefix="/api")
app.include_router(edits.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(separations.router, prefix="/api")
