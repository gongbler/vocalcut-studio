"""데모 모드 제한 = 무료 공용 서버를 지키는 규칙.

공개 사이트에서는 누가 몇 시간짜리 영상을 올리거나 작업을 수십 개 걸어도 서버가 버텨야 한다.
평소 모드(DEMO_MODE 꺼짐)에서는 아무 제한도 걸지 않는다.

값은 모두 환경 변수로 바꿀 수 있다 (config.py 참고) → 더 큰 서버(C안)로 옮기면 숫자만 키우면 된다.
"""
from __future__ import annotations

from app.core import config


class DemoLimitError(Exception):
    """데모 제한에 걸림. status_code 와 사용자에게 보여줄 문장을 함께 가진다."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _minutes(sec: float) -> str:
    """180 → '3분', 90 → '90초' (사람이 읽기 좋은 길이)."""
    return f"{int(sec // 60)}분" if sec >= 60 and sec % 60 == 0 else f"{int(sec)}초"


def upload_max_bytes() -> int:
    return config.DEMO_MAX_UPLOAD_BYTES if config.DEMO_MODE else config.MAX_UPLOAD_BYTES


def check_media_duration(duration_sec: float) -> None:
    """올린 파일의 길이 (데모: 5분 이하)."""
    if config.DEMO_MODE and duration_sec > config.DEMO_MAX_MEDIA_SEC:
        raise DemoLimitError(413, f"데모 버전에서는 {_minutes(config.DEMO_MAX_MEDIA_SEC)} 이하의 파일만 올릴 수 있어요.")


def check_ai_duration(duration_sec: float, what: str) -> None:
    """무거운 AI 작업(보컬 분리·자막)을 할 수 있는 길이 (데모: 3분 이하)."""
    if config.DEMO_MODE and duration_sec > config.DEMO_MAX_AI_SEC:
        raise DemoLimitError(
            413,
            f"데모 버전의 {what} 기능은 {_minutes(config.DEMO_MAX_AI_SEC)} 이하의 파일만 쓸 수 있어요. "
            f"'자르기'로 짧게 만든 뒤 다시 시도해 보세요.",
        )


def check_queue(active_total: int, active_mine: int) -> None:
    """작업 줄 서기: 한 사람당 동시에 1개, 서버 전체로는 DEMO_MAX_ACTIVE_JOBS 개까지."""
    if not config.DEMO_MODE:
        return
    if active_mine >= 1:
        raise DemoLimitError(429, "이미 진행 중인 작업이 있어요. 끝난 뒤에 다시 시도해 주세요.")
    if active_total >= config.DEMO_MAX_ACTIVE_JOBS:
        raise DemoLimitError(429, "지금 다른 사용자들의 작업이 많아요. 잠시 후 다시 시도해 주세요.")


def describe() -> dict | None:
    """화면 안내용 요약 (평소 모드에서는 None)."""
    if not config.DEMO_MODE:
        return None
    return {
        "upload_mb": config.DEMO_MAX_UPLOAD_BYTES // 1024**2,
        "media_minutes": config.DEMO_MAX_MEDIA_SEC / 60,
        "ai_minutes": config.DEMO_MAX_AI_SEC / 60,
        "file_ttl_minutes": config.DEMO_FILE_TTL_SEC / 60,
    }
