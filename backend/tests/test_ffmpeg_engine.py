import shutil
from pathlib import Path

import pytest

from app.services.engines.base import MediaProbeError
from app.services.engines.media.ffmpeg_engine import FFmpegEngine, _parse_fps
from app.services.engines.registry import get_media_engine
from tests.conftest import requires_ffmpeg

# ---------- 순수 함수 테스트 (FFmpeg 없이도 실행됨) ----------

@pytest.mark.parametrize(
    "rate, expected",
    [("25/1", 25.0), ("30000/1001", 29.97), ("0/0", None), (None, None), ("abc", None)],
)
def test_parse_fps(rate, expected):
    assert _parse_fps(rate) == expected


# ---------- 실제 FFmpeg 호출 테스트 ----------

@requires_ffmpeg
def test_registry_returns_ffmpeg_engine():
    engine = get_media_engine()
    assert engine.name == "ffmpeg"


@requires_ffmpeg
def test_probe_audio_only(sine_wav: Path):
    info = FFmpegEngine().probe(sine_wav)

    assert info.has_audio and not info.has_video
    assert info.duration_sec == pytest.approx(2.0, abs=0.05)
    assert info.audio.sample_rate == 44100
    assert info.audio.channels == 2


@requires_ffmpeg
def test_probe_video_with_audio(test_mp4: Path):
    info = FFmpegEngine().probe(test_mp4)

    assert info.has_video and info.has_audio
    assert (info.video.width, info.video.height) == (320, 240)
    assert info.video.fps == pytest.approx(25.0)
    assert info.video.codec == "h264"
    assert info.duration_sec == pytest.approx(1.0, abs=0.1)


@requires_ffmpeg
def test_probe_korean_filename_with_spaces(sine_wav: Path):
    # 한글 + 공백 + 쉼표가 들어간 파일 이름도 문제없이 처리해야 한다
    renamed = sine_wav.with_name("내 노래, 커버 버전.wav")
    shutil.copy(sine_wav, renamed)

    info = FFmpegEngine().probe(renamed)
    assert info.has_audio


@requires_ffmpeg
def test_probe_missing_file_raises(tmp_path: Path):
    with pytest.raises(MediaProbeError, match="파일이 없습니다"):
        FFmpegEngine().probe(tmp_path / "nope.mp3")


@requires_ffmpeg
def test_probe_non_media_file_raises(tmp_path: Path):
    fake = tmp_path / "not_audio.mp3"
    fake.write_text("이건 그냥 텍스트 파일", encoding="utf-8")

    with pytest.raises(MediaProbeError):
        FFmpegEngine().probe(fake)
