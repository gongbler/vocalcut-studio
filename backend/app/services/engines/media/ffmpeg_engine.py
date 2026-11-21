"""FFmpeg 기반 미디어 엔진.

FFmpeg 명령어는 프로젝트 전체에서 '이 파일 안에서만' 등장한다.
나중에 다른 엔진으로 교체할 때 이 파일만 새로 만들면 된다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from array import array
from pathlib import Path

from app.services.engines.base import (
    AudioStreamInfo,
    EditSpec,
    EngineNotAvailableError,
    MediaEngine,
    MediaInfo,
    MediaProbeError,
    MixSpec,
    MixTrack,
    OnProgress,
    Peaks,
    RenderError,
    VideoStreamInfo,
)

PROBE_TIMEOUT_SEC = 30
PEAKS_SAMPLE_RATE = 8000  # 파형 계산용으로 소리를 이 정도로만 풀어 받는다
MIX_SAMPLE_RATE = 44100   # 믹스할 때 모든 트랙을 이 샘플레이트로 맞춘다
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
    def render_edit(
        self,
        src: Path,
        dst: Path,
        spec: EditSpec,
        info: MediaInfo,
        on_progress: OnProgress | None = None,
    ) -> None:
        cmd = build_edit_command(self.ffmpeg, Path(src), Path(dst), spec, info)
        end = spec.end_sec if spec.end_sec is not None else info.duration_sec
        self._run_with_progress(cmd, Path(dst), total_sec=end - spec.start_sec, on_progress=on_progress)

    def _run_with_progress(
        self, cmd: list[str], dst: Path, total_sec: float, on_progress: OnProgress | None
    ) -> None:
        """FFmpeg를 실행하면서 진행률을 읽어 on_progress 로 알려준다.

        `-progress pipe:1` 옵션을 주면 FFmpeg가 표준출력(stdout)으로 이런 줄을 계속 보낸다:
            out_time_us=1234567    ← 지금까지 만든 결과물의 길이 (마이크로초)
            progress=continue      ← 마지막엔 progress=end
        """
        cmd = [*cmd[:-1], "-progress", "pipe:1", "-nostats", cmd[-1]]

        # 에러 메시지(stderr)는 임시 파일로 받는다.
        # (stdout 과 stderr 를 둘 다 파이프로 받으면, 안 읽는 쪽이 가득 차서 FFmpeg가 멈출 수 있다)
        with tempfile.TemporaryFile() as err_file:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file)
            deadline = time.monotonic() + RENDER_TIMEOUT_SEC
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:  # FFmpeg가 줄을 보낼 때마다 반복
                    if time.monotonic() > deadline:
                        proc.kill()
                        raise RenderError("렌더링 시간이 초과되었습니다.")
                    key, _, value = raw.decode("ascii", "replace").strip().partition("=")
                    if key == "out_time_us" and on_progress and total_sec > 0 and value.isdigit():
                        on_progress(min(int(value) / 1_000_000 / total_sec, 0.99))
                proc.wait()
            except BaseException:
                proc.kill()
                proc.wait()
                dst.unlink(missing_ok=True)
                raise

            if proc.returncode != 0:
                dst.unlink(missing_ok=True)  # 반쯤 만들어진 결과물 삭제
                err_file.seek(0)
                err = err_file.read().decode("utf-8", errors="replace").strip()
                last_lines = "\n".join(err.splitlines()[-5:])  # 마지막 몇 줄에 원인이 있다
                raise RenderError(f"FFmpeg 렌더링 실패: {last_lines}")

        if on_progress:
            on_progress(1.0)

    # ------------------------------------------------------------------
    def render_mix(self, dst: Path, spec: MixSpec, on_progress: OnProgress | None = None) -> None:
        cmd = build_mix_command(self.ffmpeg, Path(dst), spec)
        end = spec.end_sec if spec.end_sec is not None else spec.mix_length
        self._run_with_progress(cmd, Path(dst), total_sec=end - spec.start_sec, on_progress=on_progress)

    # ------------------------------------------------------------------
    def extract_peaks(self, path: Path, peaks_per_sec: float) -> Peaks:
        """FFmpeg로 소리를 '숫자 흐름'으로 풀어 받으면서 구간별 최대값만 남긴다.

        - 모노(-ac 1), 8000Hz(-ar)로 줄여서 받는다 → 파형 모양에는 충분하고 처리량은 1/11
        - s16le = 숫자 하나가 2바이트 정수(-32768 ~ 32767)인 날(raw) 오디오
        - 전체를 메모리에 올리지 않고 조각조각 읽으며 계산 → 2시간짜리 영상도 메모리를 거의 안 씀
        """
        samples_per_peak = max(1, round(PEAKS_SAMPLE_RATE / peaks_per_sec))
        bytes_per_peak = samples_per_peak * 2
        cmd = [
            self.ffmpeg, "-nostdin", "-v", "error",
            "-i", str(path),
            "-vn", "-ac", "1", "-ar", str(PEAKS_SAMPLE_RATE),
            "-f", "s16le", "-",  # "-" = 파일 대신 표준출력으로 보내기
        ]
        values: list[float] = []
        buffer = b""
        with tempfile.TemporaryFile() as err_file:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file)
            assert proc.stdout is not None
            try:
                while chunk := proc.stdout.read(bytes_per_peak * 1024):
                    buffer += chunk
                    usable = len(buffer) - len(buffer) % bytes_per_peak
                    values.extend(_peaks_from_pcm(buffer[:usable], samples_per_peak))
                    buffer = buffer[usable:]
                if len(buffer) >= 2:  # 마지막 남은 자투리 구간
                    values.extend(_peaks_from_pcm(buffer[: len(buffer) - len(buffer) % 2], samples_per_peak))
                proc.wait(timeout=PROBE_TIMEOUT_SEC)
            except BaseException:
                proc.kill()
                proc.wait()
                raise
            if proc.returncode != 0:
                err_file.seek(0)
                err = err_file.read().decode("utf-8", errors="replace").strip()
                raise MediaProbeError(f"파형을 만들 수 없습니다: {err.splitlines()[-1] if err else ''}")

        return Peaks(
            duration_sec=len(values) * samples_per_peak / PEAKS_SAMPLE_RATE,
            peaks_per_sec=PEAKS_SAMPLE_RATE / samples_per_peak,
            values=values,
        )

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


def _track_chain(index: int, t: MixTrack) -> str:
    """트랙 하나에 적용할 필터 줄: [입력] → 형식 통일 → 싱크 → EQ → 볼륨 → [t0]"""
    f = [
        f"[{index}:a:0]aresample={MIX_SAMPLE_RATE}",
        # 모노/스테레오, 샘플 형식이 제각각이어도 섞을 수 있게 똑같이 맞춘다
        "aformat=sample_fmts=fltp:channel_layouts=stereo",
    ]
    if t.offset_sec > 0:    # 밀기: 앞에 무음을 붙인다 (adelay 단위는 ms, all=1 → 모든 채널에)
        f.append(f"adelay={round(t.offset_sec * 1000)}:all=1")
    elif t.offset_sec < 0:  # 당기기: 앞부분을 잘라내고 시간을 0부터 다시 센다
        f += [f"atrim=start={-t.offset_sec:.3f}", "asetpts=PTS-STARTPTS"]
    if t.eq_low_db:
        f.append(f"bass=g={t.eq_low_db:g}:f=100")                    # 저음 선반(shelf) 필터
    if t.eq_mid_db:
        f.append(f"equalizer=f=1000:t=q:w=1:g={t.eq_mid_db:g}")      # 1kHz 중심 종 모양(peak) 필터
    if t.eq_high_db:
        f.append(f"treble=g={t.eq_high_db:g}:f=8000")                # 고음 선반 필터
    if t.volume_db:
        f.append(f"volume={t.volume_db:g}dB")
    return ",".join(f) + f"[t{index}]"


def build_mix_command(ffmpeg: str, dst: Path, spec: MixSpec) -> list[str]:
    """믹스 주문서를 FFmpeg filter_complex(필터 연결도)로 번역한다.

      [0] 보컬 ─ 싱크 ─ EQ ─ 볼륨 ─┐
      [1] MR   ─ 싱크 ─ EQ ─ 볼륨 ─┼─ amix(더하기) ─ 구간 자르기 ─ 페이드 ─ 리미터 ─ [out]
      [2] 내목소리 ─ ...         ─┘
    """
    if not spec.tracks:
        raise RenderError("섞을 트랙이 없습니다.")
    out_ext = dst.suffix.lower()
    if out_ext not in _AUDIO_CODECS:
        raise RenderError(f"믹스는 MP3/WAV로만 내보낼 수 있습니다: {out_ext}")

    end = spec.end_sec if spec.end_sec is not None else spec.mix_length
    length = end - spec.start_sec

    cmd = [ffmpeg, "-y", "-nostdin", "-v", "error"]
    for t in spec.tracks:
        cmd += ["-i", str(t.path)]

    chains = [_track_chain(i, t) for i, t in enumerate(spec.tracks)]
    labels = "".join(f"[t{i}]" for i in range(len(spec.tracks)))
    # normalize=0: 트랙 수로 나누지 않고 '그대로 더한다' → 설정한 볼륨이 그대로 유지됨
    mixer = f"amix=inputs={len(spec.tracks)}:duration=longest:normalize=0"

    master = [f"atrim=start={spec.start_sec:.3f}:end={end:.3f}", "asetpts=PTS-STARTPTS"]
    if spec.fade_in_sec > 0:
        master.append(f"afade=t=in:st=0:d={spec.fade_in_sec:g}")
    if spec.fade_out_sec > 0:
        master.append(f"afade=t=out:st={max(length - spec.fade_out_sec, 0):.3f}:d={spec.fade_out_sec:g}")
    if spec.limiter:
        # -1dBFS(≈0.891) 넘는 소리를 순간적으로 눌러 '찢어지는 소리(클리핑)'를 막는다
        # level=disabled: 전체 음량을 임의로 키우지 않음 / latency=1: 리미터가 만드는 미세한 지연 보정
        master.append("alimiter=limit=0.891:level=disabled:latency=1")

    graph = ";".join(chains) + f";{labels}{mixer}," + ",".join(master) + "[out]"
    cmd += ["-filter_complex", graph, "-map", "[out]", *_AUDIO_CODECS[out_ext], str(dst)]
    return cmd


def _peaks_from_pcm(data: bytes, samples_per_peak: int) -> list[float]:
    """2바이트 정수 오디오를 samples_per_peak 개씩 묶어, 묶음마다 가장 큰 크기(0~1)를 구한다."""
    samples = array("h")  # "h" = 2바이트 부호 있는 정수 배열 (파이썬 내장, C 속도)
    samples.frombytes(data)
    if sys.byteorder == "big":  # s16le 는 little-endian. 대부분의 PC는 little 이라 해당 없음
        samples.byteswap()
    out = []
    for i in range(0, len(samples), samples_per_peak):
        block = samples[i : i + samples_per_peak]
        loudest = max(max(block), -min(block))  # 위아래 중 더 큰 쪽
        out.append(round(min(loudest / 32768, 1.0), 3))
    return out


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
