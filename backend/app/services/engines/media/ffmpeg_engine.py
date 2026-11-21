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
    EditSpec,
    EngineNotAvailableError,
    MediaEngine,
    MediaInfo,
    MediaProbeError,
    RenderError,
    VideoStreamInfo,
)

PROBE_TIMEOUT_SEC = 30
RENDER_TIMEOUT_SEC = 60 * 60  # 긴 영상도 저사양 PC에서 끝낼 수 있게 넉넉히 1시간

# 출력 확장자별 인코딩 설정
_AUDIO_CODECS = {
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    ".wav": ["-c:a", "pcm_s16le"],  # 무손실 (용량 큼)
}
_VIDEO_ARGS = [
    "-c:v", "libx264",
    "-preset", "veryfast",  # 저사양 PC를 고려해 속도 우선 (화질 차이는 crf로 보완)
    "-crf", "20",           # 화질: 숫자가 작을수록 고화질·큰 용량 (18~23 권장)
    "-pix_fmt", "yuv420p",  # 대부분의 플레이어/브라우저에서 재생되는 색 형식
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",  # 웹에서 다 받기 전에 재생 시작 가능하게
]


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
    def render_edit(self, src: Path, dst: Path, spec: EditSpec, info: MediaInfo) -> None:
        cmd = build_edit_command(self.ffmpeg, Path(src), Path(dst), spec, info)
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=RENDER_TIMEOUT_SEC, check=False
            )
        except subprocess.TimeoutExpired as e:
            Path(dst).unlink(missing_ok=True)
            raise RenderError("렌더링 시간이 초과되었습니다.") from e

        if result.returncode != 0:
            Path(dst).unlink(missing_ok=True)  # 반쯤 만들어진 결과물 삭제
            err = result.stderr.decode("utf-8", errors="replace").strip()
            last_lines = "\n".join(err.splitlines()[-5:])  # 마지막 몇 줄에 원인이 있다
            raise RenderError(f"FFmpeg 렌더링 실패: {last_lines}")

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


def build_edit_command(
    ffmpeg: str, src: Path, dst: Path, spec: EditSpec, info: MediaInfo
) -> list[str]:
    """편집 주문서(EditSpec)를 FFmpeg 명령어 리스트로 번역한다.

    실행과 분리된 순수 함수라서, FFmpeg를 돌리지 않고도 '명령이 맞게 만들어지는지' 테스트할 수 있다.
    """
    end = spec.end_sec if spec.end_sec is not None else info.duration_sec
    length = end - spec.start_sec  # 잘라낸 결과물의 길이
    out_ext = dst.suffix.lower()

    cmd = [
        ffmpeg,
        "-y",             # 같은 이름 파일이 있으면 덮어쓰기
        "-nostdin",       # 키보드 입력을 기다리며 멈추는 일 방지 (서버에서 실행하므로 필수)
        "-v", "error",
        # -ss 를 -i '앞'에 두면 해당 지점으로 바로 점프(빠름). 다시 인코딩하므로 정확도도 유지된다.
        "-ss", f"{spec.start_sec:.3f}",
        "-i", str(src),
        "-t", f"{length:.3f}",  # 시작점부터 이만큼만
    ]

    # 오디오 필터 체인: 쉼표(,)로 이어서 순서대로 적용된다 → 볼륨 → 페이드인 → 페이드아웃
    # 잘라낸 결과물의 시간은 0초부터 다시 시작하므로 페이드 시점도 0 기준으로 계산한다.
    filters: list[str] = []
    if spec.volume_db:
        filters.append(f"volume={spec.volume_db:g}dB")
    if spec.fade_in_sec > 0:
        filters.append(f"afade=t=in:st=0:d={spec.fade_in_sec:g}")
    if spec.fade_out_sec > 0:
        start_out = max(length - spec.fade_out_sec, 0)
        filters.append(f"afade=t=out:st={start_out:.3f}:d={spec.fade_out_sec:g}")
    if filters and info.has_audio:
        cmd += ["-af", ",".join(filters)]

    if out_ext == ".mp4":
        if not info.has_video:
            raise RenderError("영상 트랙이 없는 파일은 MP4로 내보낼 수 없습니다.")
        # 첫 번째 영상 트랙 + (있다면) 첫 번째 오디오 트랙만 사용. '?' = 없어도 에러 내지 않기
        cmd += ["-map", "0:v:0", "-map", "0:a:0?", *_VIDEO_ARGS]
    elif out_ext in _AUDIO_CODECS:
        if not info.has_audio:
            raise RenderError("오디오 트랙이 없는 파일은 오디오로 내보낼 수 없습니다.")
        cmd += ["-vn", "-map", "0:a:0", *_AUDIO_CODECS[out_ext]]  # -vn = 영상(앨범 커버 포함) 제외
    else:
        raise RenderError(f"지원하지 않는 출력 형식입니다: {out_ext}")

    cmd.append(str(dst))
    return cmd


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
