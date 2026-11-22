"""엔진 '배정 담당'.

설정(config)을 보고 어떤 엔진을 쓸지 결정해 건네준다.
서비스 코드는 get_..._engine() 만 부르고, 구체적인 엔진 클래스는 모른다.
"""
from __future__ import annotations

from functools import lru_cache

from app.core import config
from app.services.engines.base import EngineError, MediaEngine, SeparatorEngine, TranscriberEngine


@lru_cache  # 엔진은 한 번만 만들어서 계속 재사용한다
def get_media_engine() -> MediaEngine:
    name = config.MEDIA_ENGINE
    if name == "ffmpeg":
        from app.services.engines.media.ffmpeg_engine import FFmpegEngine
        return FFmpegEngine()
    raise EngineError(f"알 수 없는 미디어 엔진: {name!r}")


@lru_cache
def get_separator_engine() -> SeparatorEngine:
    name = config.SEPARATOR_ENGINE
    if name == "demucs":
        # demucs_engine 은 torch 를 import 하지 않는다 → 서버 메모리에 영향 없음
        from app.services.engines.separator.demucs_engine import DemucsSeparator
        return DemucsSeparator()
    raise EngineError(f"알 수 없는 분리 엔진: {name!r}")


@lru_cache
def get_transcriber_engine() -> TranscriberEngine:
    name = config.TRANSCRIBER_ENGINE
    if name == "whisper":
        # whisper_engine 은 faster_whisper 를 import 하지 않는다 → 서버 메모리에 영향 없음
        from app.services.engines.transcriber.whisper_engine import WhisperTranscriber
        return WhisperTranscriber()
    raise EngineError(f"알 수 없는 자막 엔진: {name!r}")
