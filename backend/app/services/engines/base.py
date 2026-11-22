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
class MixTrack:
    """믹스에 들어갈 트랙 하나의 설정."""
    path: Path
    duration_sec: float
    volume_db: float = 0.0
    offset_sec: float = 0.0   # 싱크: +0.2 = 0.2초 늦게 시작(밀기), -0.2 = 앞 0.2초를 잘라 당기기
    eq_low_db: float = 0.0    # 저음 (약 100Hz 아래)
    eq_mid_db: float = 0.0    # 중음 (약 1kHz 부근, 목소리의 몸통)
    eq_high_db: float = 0.0   # 고음 (약 8kHz 위, 숨소리·선명함)

    @property
    def end_sec(self) -> float:
        """믹스 타임라인에서 이 트랙이 끝나는 시점."""
        return max(self.offset_sec + self.duration_sec, 0.0)


@dataclass(frozen=True)
class MixSpec:
    """'이 트랙들을 이렇게 섞어 주세요' 주문서."""
    tracks: tuple[MixTrack, ...]
    start_sec: float = 0.0          # 결과물로 내보낼 구간 (미리듣기는 짧은 구간만)
    end_sec: float | None = None    # None = 가장 긴 트랙의 끝까지
    fade_in_sec: float = 0.0        # 전체 믹스의 페이드 인/아웃
    fade_out_sec: float = 0.0
    limiter: bool = True            # 여러 트랙을 더하면 소리가 커져 깨질 수 있음 → 자동으로 눌러줌

    @property
    def mix_length(self) -> float:
        return max((t.end_sec for t in self.tracks), default=0.0)


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


class SeparationError(EngineError):
    """보컬/MR 분리 실패. user_message 는 화면에 그대로 보여줘도 되는 문장."""

    def __init__(self, message: str, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


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

    @abstractmethod
    def render_mix(self, dst: Path, spec: MixSpec, on_progress: OnProgress | None = None) -> None:
        """여러 오디오 트랙을 spec 대로 섞어 dst 에 저장한다 (.mp3 / .wav)."""


# ---------- 보컬/MR 분리 엔진 규격서 ----------

@dataclass(frozen=True)
class StemPaths:
    """분리 결과 파일들."""
    vocals: Path
    instrumental: Path  # 보컬을 뺀 나머지 전부 (MR)


@dataclass(frozen=True)
class Availability:
    ok: bool
    reason: str = ""


class SeparatorEngine(ABC):
    """보컬/MR 분리 엔진이 갖춰야 할 기능.

    Demucs 를 상업용 모델로 바꿀 때는 이 규격을 지키는 새 엔진만 만들면 된다.
    """

    name: str

    @abstractmethod
    def availability(self) -> Availability:
        """사용 가능한지 '가볍게' 확인한다. (무거운 AI 라이브러리를 불러오면 안 된다)"""

    @abstractmethod
    def separate(
        self,
        src: Path,
        out_dir: Path,
        on_progress: OnProgress | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> StemPaths:
        """src 의 소리를 보컬/MR 로 나눠 out_dir 에 저장한다. 오래 걸린다(곡 길이의 수 배).

        on_stage: 단계가 바뀔 때 화면에 보여줄 설명을 알려준다 (예: "AI 모델 불러오는 중").
        """


# ---------- 자막 받아쓰기 엔진 규격서 ----------

@dataclass(frozen=True)
class TranscriptSegment:
    """자막 한 줄: 시작/끝 시간(초)과 글자."""
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    language: str                         # 받아 적을 때 쓴 언어
    segments: tuple[TranscriptSegment, ...]
    detected_language: str | None = None  # AI 가 따로 들어 보고 판단한 실제 언어
    detected_probability: float = 0.0     # 그 판단의 확신도 (0~1)


class TranscriptionError(EngineError):
    """받아쓰기 실패. user_message 는 화면에 그대로 보여줘도 되는 문장."""

    def __init__(self, message: str, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


class TranscriberEngine(ABC):
    """자막 받아쓰기 엔진이 갖춰야 할 기능.

    Whisper 를 다른 음성 인식 엔진(클라우드 API 등)으로 바꿀 때는 이 규격을 지키는 새 엔진만 만들면 된다.
    """

    name: str
    models: dict[str, str]  # 고를 수 있는 모델 → 화면 설명 (예: {"small": "정확", "base": "빠름"})
    default_model: str

    @abstractmethod
    def availability(self) -> Availability:
        """사용 가능한지 '가볍게' 확인한다. (무거운 AI 라이브러리를 불러오면 안 된다)"""

    @abstractmethod
    def transcribe(
        self,
        src: Path,
        model: str,
        language: str | None = None,
        on_progress: OnProgress | None = None,
        on_stage: Callable[[str], None] | None = None,
        on_segment: Callable[[TranscriptSegment], None] | None = None,
        isolated_voice: bool = False,
    ) -> Transcript:
        """src 의 말/노래를 받아 적는다. language=None 이면 자동 감지.

        isolated_voice: 반주 없이 목소리만 있는 소리(분리된 보컬)인지. 아니면 반주 속 노래를 놓치지 않게
                        목소리 감지 기준을 낮춘다.

        on_segment: 한 줄이 완성될 때마다 바로 알려준다 (화면에 '지금 받아 적는 중인 줄' 표시용).
        """
