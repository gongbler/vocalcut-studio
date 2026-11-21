"""서버 상태 확인(Health Check) API.

프론트엔드가 "서버 살아있어?"라고 물어보면 대답하는 창구.
덤으로 FFmpeg, AI 보컬 분리를 쓸 수 있는지도 알려준다.
(보컬 분리 확인은 '설치 여부'만 본다 — torch 를 불러오지 않아 가볍다)
"""
import platform
import shutil

from fastapi import APIRouter, Depends

from app.api.deps import get_separator
from app.core.config import APP_NAME, APP_VERSION
from app.services.engines.base import SeparatorEngine

router = APIRouter()


@router.get("/health")
def health(separator: SeparatorEngine = Depends(get_separator)) -> dict:
    ffmpeg_path = shutil.which("ffmpeg")  # PATH에서 ffmpeg 실행 파일을 찾는다
    sep = separator.availability()
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "python": platform.python_version(),
        "ffmpeg": {
            "available": ffmpeg_path is not None,
            "path": ffmpeg_path,
        },
        "separator": {
            "engine": separator.name,
            "available": sep.ok,
            "reason": sep.reason or None,
        },
    }
