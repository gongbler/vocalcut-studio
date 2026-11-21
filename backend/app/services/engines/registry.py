"""엔진 '배정 담당'.

설정(config.MEDIA_ENGINE)을 보고 어떤 엔진을 쓸지 결정해 건네준다.
서비스 코드는 get_media_engine()만 부르고, 구체적인 엔진 클래스는 모른다.
"""
from __future__ import annotations

from functools import lru_cache

from app.core import config
from app.services.engines.base import EngineError, MediaEngine


@lru_cache  # 엔진은 한 번만 만들어서 계속 재사용한다
def get_media_engine() -> MediaEngine:
    name = config.MEDIA_ENGINE
    if name == "ffmpeg":
        from app.services.engines.media.ffmpeg_engine import FFmpegEngine
        return FFmpegEngine()
    raise EngineError(f"알 수 없는 미디어 엔진: {name!r}")
