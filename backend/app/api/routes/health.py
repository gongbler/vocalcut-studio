"""서버 상태 확인(Health Check) API.

프론트엔드가 "서버 살아있어?"라고 물어보면 대답하는 창구.
덤으로 FFmpeg가 이 서버에서 실행 가능한지도 알려준다.
"""
import platform
import shutil

from fastapi import APIRouter

from app.core.config import APP_NAME, APP_VERSION

router = APIRouter()


@router.get("/health")
def health() -> dict:
    ffmpeg_path = shutil.which("ffmpeg")  # PATH에서 ffmpeg 실행 파일을 찾는다
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "python": platform.python_version(),
        "ffmpeg": {
            "available": ffmpeg_path is not None,
            "path": ffmpeg_path,
        },
    }
