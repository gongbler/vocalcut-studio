"""FFmpeg 기반 미디어 엔진.

FFmpeg 명령어는 프로젝트 전체에서 '이 파일 안에서만' 등장한다.
나중에 다른 엔진으로 교체할 때 이 파일만 새로 만들면 된다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from app.services.engines.base import (
    AudioStreamInfo,
    EngineNotAvailableError,
    MediaEngine,
    MediaInfo,
    MediaProbeError,
    VideoStreamInfo,
)

PROBE_TIMEOUT_SEC = 30


class FFmpegEngine(MediaEngine):
    name = "ffmpeg"

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> None:
        # PATH에서 실행 파일의 실제 위치를 찾는다. 없으면 바로 알려준다.
        self.ffmpeg = shutil.which(ffmpeg_bin)
        self.ffprobe = shutil.which(ffprobe_bin)
        if not self.ffmpeg or not self.ffprobe:
            raise EngineNotAvailableError(
                "ffmpeg/ffprobe를 찾을 수 없습니다. 설치 후 PATH에 등록했는지, "
                "터미널을 새로 열었는지 확인하세요."
            )

    # ------------------------------------------------------------------
    def probe(self, path: Path) -> MediaInfo:
        path = Path(path)
        if not path.is_file():
            raise MediaProbeError(f"파일이 없습니다: {path}")

        cmd = [
            self.ffprobe,
            "-v", "error",              # 에러만 출력
            "-print_format", "json",    # 결과를 JSON으로
            "-show_format",             # 파일 전체 정보 (길이, 크기, 포맷)
            "-show_streams",            # 트랙별 정보 (영상/오디오)
            str(path),
        ]
        # shell=False(기본값) + 리스트 인자 → 파일 이름에 공백/한글이 있어도 안전
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=PROBE_TIMEOUT_SEC, check=False
            )
        except subprocess.TimeoutExpired as e:
            raise MediaProbeError(f"파일 분석 시간이 초과되었습니다: {path.name}") from e

        if result.returncode != 0:
            # 윈도우에서 한글 메시지가 깨지지 않도록 바이트를 직접 디코딩
            err = result.stderr.decode("utf-8", errors="replace").strip()
            raise MediaProbeError(f"미디어 파일로 인식할 수 없습니다: {path.name} ({err})")

        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        return self._to_media_info(path, data)

    # ------------------------------------------------------------------
    @staticmethod
    def _to_media_info(path: Path, data: dict) -> MediaInfo:
        """ffprobe의 JSON을 엔진 공통 형식(MediaInfo)으로 번역한다."""
        fmt = data.get("format", {})
        streams = data.get("streams", [])

        video_raw = next(
            (s for s in streams
             if s.get("codec_type") == "video"
             # 앨범 커버 이미지(mp3 안의 그림)는 영상으로 치지 않는다
             and not s.get("disposition", {}).get("attached_pic")),
            None,
        )
        audio_raw = next((s for s in streams if s.get("codec_type") == "audio"), None)

        video = None
        if video_raw:
            video = VideoStreamInfo(
                codec=video_raw.get("codec_name", "unknown"),
                width=int(video_raw.get("width", 0)),
                height=int(video_raw.get("height", 0)),
                fps=_parse_fps(video_raw.get("avg_frame_rate") or video_raw.get("r_frame_rate")),
            )

        audio = None
        if audio_raw:
            audio = AudioStreamInfo(
                codec=audio_raw.get("codec_name", "unknown"),
                sample_rate=int(audio_raw.get("sample_rate", 0)),
                channels=int(audio_raw.get("channels", 0)),
            )

        if video is None and audio is None:
            raise MediaProbeError(f"영상/오디오 트랙이 없는 파일입니다: {path.name}")

        return MediaInfo(
            path=path,
            format_name=fmt.get("format_name", "unknown"),
            duration_sec=float(fmt.get("duration", 0.0)),
            size_bytes=int(fmt.get("size", path.stat().st_size)),
            video=video,
            audio=audio,
        )


def _parse_fps(rate: str | None) -> float | None:
    """'30000/1001' 같은 분수 문자열을 29.97 같은 숫자로 바꾼다."""
    if not rate or rate == "0/0":
        return None
    num, _, den = rate.partition("/")
    try:
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3)
