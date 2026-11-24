"""서버 상태 확인(Health Check) API.

프론트엔드가 "서버 살아있어?"라고 물어보면 대답하는 창구.
덤으로 FFmpeg, AI 보컬 분리, AI 자막을 쓸 수 있는지도 알려준다.
(보컬 분리 확인은 '설치 여부'만 본다 — torch 를 불러오지 않아 가볍다)
"""
import platform
import shutil

from fastapi import APIRouter, Depends

from app.api.deps import get_separator, get_transcriber, get_workspace
from app.core import config, demo_limits
from app.core.config import APP_NAME, APP_VERSION
from app.services import separation_service
from app.services.engines.base import SeparatorEngine, TranscriberEngine
from app.storage.workspace import Workspace

router = APIRouter()


@router.get("/health")
def health(
    separator: SeparatorEngine = Depends(get_separator),
    transcriber: TranscriberEngine = Depends(get_transcriber),
    ws: Workspace = Depends(get_workspace),
) -> dict:
    ffmpeg_path = shutil.which("ffmpeg")  # PATH에서 ffmpeg 실행 파일을 찾는다
    sep = separator.availability()
    asr = transcriber.availability()
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
            # 이 PC에서 실제로 걸린 시간 ÷ 곡 길이 (기록이 없으면 null)
            "speed_ratio": separation_service.speed_ratio(ws),
        },
        "transcriber": {
            "engine": transcriber.name,
            "available": asr.ok,
            "reason": asr.reason or None,
            "models": [{"id": k, "label": v} for k, v in transcriber.models.items()],
            "default_model": transcriber.default_model,
        },
    }


@router.get("/session")
def session() -> dict:
    """화면이 처음 열릴 때 가장 먼저 부르는 주소.

    데모 모드에서는 이 응답과 함께 방문자 번호표(쿠키)가 발급된다. 화면이 여러 요청을 동시에 보내기 전에
    번호표를 먼저 받아 두어야, 요청마다 다른 번호가 생겨 파일이 흩어지는 일이 없다.
    """
    return {"demo": config.DEMO_MODE, "limits": demo_limits.describe()}
