"""디스크 공간 확인 — 무거운 작업을 '시작하기 전에' 공간이 충분한지 본다.

왜? 보컬 분리는 3분짜리 곡에도 임시 파일·결과물로 150MB 넘게 쓴다.
디스크가 도중에 가득 차면 작업은 반쯤 쓴 파일을 남기고 알 수 없는 오류로 실패하고,
심하면 윈도우 자체가 느려진다. 시작 전에 "공간이 부족해요"라고 알려 주는 편이 훨씬 낫다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

MIN_FREE_BYTES = 500 * 1024**2  # 작업이 끝난 뒤에도 최소 이만큼은 남아 있어야 한다 (윈도우·다른 프로그램 몫)

# 작업별 예상 사용량 계산용 (44.1kHz 스테레오)
_PCM16_STEREO_PER_SEC = 44100 * 2 * 2   # WAV 1초 = 약 172KB
_F32_STEREO_PER_SEC = 44100 * 2 * 4     # 분리용 임시 원본 1초 = 약 345KB


class InsufficientSpaceError(Exception):
    """디스크 공간 부족 (HTTP 507 로 바꿔 보낸다)."""


def _mb(n: float) -> str:
    return f"{n / 1024**2:,.0f}MB" if n < 1024**3 else f"{n / 1024**3:.1f}GB"


def require_free_space(path: Path, needed_bytes: float, what: str) -> None:
    """path 가 있는 디스크에 needed_bytes + 여유분이 없으면 InsufficientSpaceError."""
    free = shutil.disk_usage(path).free
    if free - needed_bytes < MIN_FREE_BYTES:
        raise InsufficientSpaceError(
            f"디스크 공간이 부족해 {what}을(를) 시작할 수 없어요. "
            f"필요: 약 {_mb(needed_bytes + MIN_FREE_BYTES)} (여유분 포함) · 남은 공간: {_mb(free)}. "
            "'📂 내 파일'에서 안 쓰는 파일을 삭제하거나 디스크를 정리한 뒤 다시 시도하세요."
        )


# ---------- 작업별 예상 사용량 (넉넉하게 1.2배) ----------

def separation_bytes(duration_sec: float) -> float:
    """임시 원본(f32) + 보컬 WAV + MR WAV."""
    return duration_sec * (_F32_STEREO_PER_SEC + 2 * _PCM16_STEREO_PER_SEC) * 1.2


def render_bytes(duration_sec: float, source_size: int) -> float:
    """편집·믹스·자막 입히기 결과물: WAV 로 내보내는 경우와 원본 영상 크기 중 큰 쪽."""
    return max(duration_sec * _PCM16_STEREO_PER_SEC, source_size) * 1.2
