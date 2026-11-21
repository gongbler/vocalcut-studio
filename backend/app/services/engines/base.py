"""엔진 '규격서(인터페이스)'.

서비스 계층은 이 파일에 정의된 타입과 메서드만 알고 있다.
FFmpeg든, 나중에 바꿀 다른 엔진이든 이 규격만 지키면 그대로 끼워 쓸 수 있다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# 엔진이 진행률(0.0~1.0)을 알려줄 때 부르는 함수
OnProgress = Callable[[float], None]


# ---------- 결과 데이터 (엔진 종류와 상관없이 같은 모양) ----------

@dataclass(frozen=True)
class VideoStreamInfo:
    codec: str
    width: int
    height: int
    fps: float | None


@dataclass(frozen=True)
class AudioStreamInfo:
    codec: str
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class MediaInfo:
    """미디어 파일 한 개의 기본 정보."""
    path: Path
    format_name: str
    duration_sec: float
    size_bytes: int
    video: VideoStreamInfo | None  # 영상 트랙이 없으면 None (예: mp3)
    audio: AudioStreamInfo | None  # 오디오 트랙이 없으면 None (예: 무음 영상)

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None


@dataclass(frozen=True)
class EditSpec:
    """'이렇게 편집해 주세요' 주문서. 엔진 종류와 상관없이 같은 모양.

    시간 단위는 모두 초(second). 페이드는 '잘라낸 결과물' 기준이다.
    """
    start_sec: float = 0.0
    end_sec: float | None = None   # None 이면 파일 끝까지
    volume_db: float = 0.0         # +6 = 약 2배 크게, -6 = 약 절반 크기
    fade_in_sec: float = 0.0
    fade_out_sec: float = 0.0


@dataclass(frozen=True)
class Peaks:
    """파형을 그리기 위한 요약 데이터.

    소리 전체(1초에 44,100개 숫자)를 보내는 대신, 짧은 구간마다 '가장 큰 소리 크기' 하나씩만 남긴다.
    values[i] = i번째 구간의 최대 크기 (0.0 = 무음 ~ 1.0 = 최대)
    """
    duration_sec: float
    peaks_per_sec: float
    values: list[float]


# ---------- 에러 (엔진 종류와 상관없이 같은 종류) ----------

class EngineError(Exception):
    """엔진 작업 중 발생한 모든 에러의 부모."""


class EngineNotAvailableError(EngineError):
    """엔진 프로그램이 설치되어 있지 않거나 찾을 수 없음."""


class MediaProbeError(EngineError):
    """파일을 분석할 수 없음 (없는 파일, 깨진 파일, 미디어가 아닌 파일 등)."""


class RenderError(EngineError):
    """편집 결과물을 만드는 중 실패."""


# ---------- 규격서 ----------

class MediaEngine(ABC):
    """영상/오디오 처리 엔진이 반드시 갖춰야 할 기능 목록."""

    #: 엔진 이름 (로그·화면 표시용)
    name: str

    @abstractmethod
    def probe(self, path: Path) -> MediaInfo:
        """파일을 분석해 길이·포맷·트랙 정보를 돌려준다."""

    @abstractmethod
    def render_edit(
        self,
        src: Path,
        dst: Path,
        spec: EditSpec,
        info: MediaInfo,
        on_progress: OnProgress | None = None,
    ) -> None:
        """src 를 spec 대로 편집해 dst 에 저장한다.

        출력 형식은 dst 의 확장자로 결정한다 (.mp4 = 영상, .mp3 = 오디오).
        spec 값이 올바른지는 호출하는 쪽(서비스)이 미리 검사한다.
        on_progress 가 주어지면 진행률(0.0~1.0)을 수시로 알려준다.
        """

    @abstractmethod
    def extract_peaks(self, path: Path, peaks_per_sec: float) -> Peaks:
        """오디오의 파형 요약(Peaks)을 계산한다. 영상이면 소리 트랙을 사용한다."""
