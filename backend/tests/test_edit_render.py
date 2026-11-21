"""편집 렌더링 테스트.

'결과 파일이 생겼다'에서 끝내지 않고, 실제로 소리가 작아졌는지·페이드가 됐는지를
FFmpeg의 volumedetect 필터로 '측정'해서 확인한다.
"""
import re
import subprocess
from pathlib import Path

import pytest

from app.services.edit_service import EditValidationError, validate_spec
from app.services.engines.base import EditSpec, RenderError
from app.services.engines.media.ffmpeg_engine import FFmpegEngine, build_edit_command
from tests.conftest import FFMPEG, requires_ffmpeg


def max_volume_db(path: Path, start: float = 0.0, length: float | None = None) -> float:
    """파일(또는 일부 구간)에서 가장 큰 소리의 크기(dB)를 측정한다."""
    cmd = [FFMPEG, "-nostdin", "-ss", str(start), "-i", str(path)]
    if length:
        cmd += ["-t", str(length)]
    cmd += ["-af", "volumedetect", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, check=True).stderr.decode("utf-8", "replace")
    m = re.search(r"max_volume: (-?[\d.]+|-inf) dB", err)
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


# ---------- 주문서 검사 (FFmpeg 불필요) ----------

class TestValidateSpec:
    def test_fills_end_with_duration(self):
        assert validate_spec(EditSpec(start_sec=1), duration=10).end_sec == 10

    @pytest.mark.parametrize("spec, msg", [
        (EditSpec(start_sec=5, end_sec=3), "0.1초 이상 뒤"),
        (EditSpec(end_sec=20), "파일 길이"),
        (EditSpec(volume_db=50), "볼륨"),
        (EditSpec(start_sec=0, end_sec=2, fade_in_sec=1.5, fade_out_sec=1.5), "페이드"),
    ])
    def test_rejects_invalid(self, spec, msg):
        with pytest.raises(EditValidationError, match=msg):
            validate_spec(spec, duration=10)


# ---------- 명령어 조립 (FFmpeg 불필요) ----------

def _info(has_video=False, duration=10.0):
    from app.services.engines.base import AudioStreamInfo, MediaInfo, VideoStreamInfo
    return MediaInfo(
        path=Path("x"), format_name="x", duration_sec=duration, size_bytes=1,
        video=VideoStreamInfo("h264", 320, 240, 25) if has_video else None,
        audio=AudioStreamInfo("aac", 44100, 2),
    )


def test_command_builds_filter_chain_in_order():
    spec = EditSpec(start_sec=2, end_sec=8, volume_db=-6, fade_in_sec=1, fade_out_sec=2)
    cmd = build_edit_command("ffmpeg", Path("in.wav"), Path("out.mp3"), spec, _info())

    assert cmd[cmd.index("-ss") + 1] == "2.000"
    assert cmd[cmd.index("-t") + 1] == "6.000"
    # 볼륨 → 페이드인 → 페이드아웃(6초 길이 - 2초 = 4초 지점부터)
    assert cmd[cmd.index("-af") + 1] == "volume=-6dB,afade=t=in:st=0:d=1,afade=t=out:st=4.000:d=2"


def test_command_rejects_mp4_for_audio_only():
    with pytest.raises(RenderError):
        build_edit_command("ffmpeg", Path("in.wav"), Path("out.mp4"), EditSpec(), _info())


# ---------- 실제 렌더링 ----------

@requires_ffmpeg
def test_trim_audio_length(sine_wav, tmp_path):
    engine = FFmpegEngine()
    out = tmp_path / "out.mp3"
    spec = EditSpec(start_sec=0.5, end_sec=1.5)

    engine.render_edit(sine_wav, out, spec, engine.probe(sine_wav))

    assert engine.probe(out).duration_sec == pytest.approx(1.0, abs=0.06)


@requires_ffmpeg
def test_volume_minus_6db_is_measured(sine_wav, tmp_path):
    engine = FFmpegEngine()
    out = tmp_path / "quiet.wav"

    engine.render_edit(sine_wav, out, EditSpec(volume_db=-6), engine.probe(sine_wav))

    assert max_volume_db(out) == pytest.approx(max_volume_db(sine_wav) - 6, abs=0.3)


@requires_ffmpeg
def test_fade_in_starts_silent(sine_wav, tmp_path):
    engine = FFmpegEngine()
    out = tmp_path / "fade.wav"

    engine.render_edit(sine_wav, out, EditSpec(fade_in_sec=1.0), engine.probe(sine_wav))

    # 대조군: 페이드 없는 원본은 시작 부분도 중간과 크기가 같다
    assert max_volume_db(sine_wav, 0, 0.05) == pytest.approx(max_volume_db(sine_wav, 1.2, 0.2), abs=1)

    # 페이드 인 결과물은 시작 0.05초가 중간보다 확실히(10dB 이상) 조용해야 한다
    first_50ms = max_volume_db(out, start=0, length=0.05)
    middle = max_volume_db(out, start=1.2, length=0.2)
    assert first_50ms < middle - 10


@requires_ffmpeg
def test_trim_video_keeps_video_and_audio(test_mp4, tmp_path):
    engine = FFmpegEngine()
    out = tmp_path / "cut.mp4"

    engine.render_edit(test_mp4, out, EditSpec(start_sec=0.2, end_sec=0.8), engine.probe(test_mp4))

    info = engine.probe(out)
    assert info.has_video and info.has_audio
    assert info.duration_sec == pytest.approx(0.6, abs=0.1)
