"""FastAPI 앱의 시작점.

실행: (backend 폴더에서) uvicorn app.main:app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health
from app.core.config import APP_NAME, APP_VERSION, WORKSPACE_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버가 켜질 때: 작업 폴더가 없으면 만들어 둔다
    for sub in ("uploads", "temp", "outputs"):
        (WORKSPACE_DIR / sub).mkdir(parents=True, exist_ok=True)
    yield
    # 서버가 꺼질 때 할 정리 작업은 여기에 (Step 4에서 임시 파일 정리 추가 예정)


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

# 모든 API 주소 앞에 /api 를 붙인다 → /api/health
app.include_router(health.router, prefix="/api", tags=["system"])
