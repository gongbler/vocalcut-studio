"""FastAPI 앱의 시작점.

실행: (backend 폴더에서) uvicorn app.main:app --reload
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.deps import get_workspace
from app.api.routes import edits, files, health, jobs, library, mixes, separations, subtitles
from app.core.config import APP_NAME, APP_VERSION
from app.core.logging_setup import new_error_id, setup_logging
from app.jobs.manager import JobManager
from app.services import library_service
from app.services.disk_guard import InsufficientSpaceError

setup_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버가 켜질 때: 작업 폴더를 준비하고, 작업 관리자(작업자 1명)를 만든다
    ws = get_workspace()
    ws.ensure()
    # 강제 종료로 남은 임시 파일·오래된 작업 기록만 정리 (사용자 파일은 건드리지 않음)
    cleaned = library_service.startup_cleanup(ws)
    app.state.job_manager = JobManager(ws.jobs, max_workers=1)
    # 켜질 때마다 한 줄 남긴다 → app.log 가 비어 있으면 '기록이 안 되는 것'인지 바로 알 수 있다
    logger.info("서버 시작 %s v%s · 작업 폴더 %s · 시작 정리 %s", APP_NAME, APP_VERSION, ws.root, cleaned)
    yield
    # 서버가 꺼질 때: 대기 중인 작업은 취소하고 작업자 정리
    app.state.job_manager.shutdown(wait=False)
    logger.info("서버 종료")


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)


@app.exception_handler(InsufficientSpaceError)
async def on_disk_full(request: Request, exc: InsufficientSpaceError) -> JSONResponse:
    # 507 Insufficient Storage: '저장 공간 부족'을 뜻하는 HTTP 상태 번호
    return JSONResponse(status_code=507, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def on_invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """'잘못된 요청'(422) 안내. FastAPI 기본 처리와 내용은 같다.

    다른 점: 요청에 깨진 글자(UTF-8 이 아닌 바이트)가 섞여 있으면 기본 처리는 그 글자를 답장에 그대로 넣으려다
    UTF-8 변환에 실패해 500 이 났다. 여기서는 깨진 글자를 '?' 로 바꿔 넣는다.
    """
    def clean(value: object) -> object:
        if isinstance(value, str):
            return value.encode("utf-8", "replace").decode("utf-8")
        if isinstance(value, dict):
            return {clean(k): clean(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [clean(v) for v in value]
        return value

    return JSONResponse(status_code=422, content={"detail": clean(jsonable_encoder(exc.errors()))})


@app.exception_handler(Exception)
async def on_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """예상 못 한 오류: 원인(전체 기록)은 로그 파일에, 사용자에게는 알아듣는 말 + 오류 번호만.

    기본값이면 'Internal Server Error' 라는 영어 한 줄(JSON 도 아님)만 가서 화면이 이유를 보여줄 수 없었다.
    """
    error_id = new_error_id()
    logger.error("unexpected error %s on %s %s", error_id, request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={
        "detail": f"서버에서 예상하지 못한 오류가 발생했어요 (오류 번호 {error_id}). "
                  f"logs\\app.log 에서 이 번호를 찾으면 원인을 볼 수 있어요.",
        "error_id": error_id,
    })


# 모든 API 주소 앞에 /api 를 붙인다 → /api/health, /api/files ...
app.include_router(health.router, prefix="/api", tags=["system"])
app.include_router(files.router, prefix="/api")
app.include_router(edits.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(separations.router, prefix="/api")
app.include_router(mixes.router, prefix="/api")
app.include_router(subtitles.router, prefix="/api")
app.include_router(library.router, prefix="/api")
