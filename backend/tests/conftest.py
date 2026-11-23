"""테스트 공용 준비물(fixture).

실제 노래 파일 대신, FFmpeg로 '삐-' 소리와 테스트 화면을 즉석에서 만들어 쓴다.
→ 저작권 걱정 없고, 저장소에 큰 파일을 올릴 필요도 없다.
"""
import os
import shutil
import subprocess
from pathlib import Path

# 테스트 중 일부러 내는 오류가 실제 서버 기록(logs/app.log)에 섞이지 않게 파일 기록을 끈다
# (app 을 import 하기 '전'에 설정해야 해서 맨 위에 둔다)
os.environ.setdefault("VOCALCUT_LOG_FILE", "")

import pytest

FFMPEG = shutil.which("ffmpeg")

requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg가 PATH에 없음")


def _make(args: list[str], out: Path) -> Path:
    subprocess.run([FFMPEG, "-y", "-v", "error", *args, str(out)], check=True, timeout=60)
    return out


@pytest.fixture
def sine_wav(tmp_path: Path) -> Path:
    """2초짜리 440Hz 사인파 WAV (44.1kHz, 스테레오)."""
    return _make(
        ["-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=44100",
         "-ac", "2"],
        tmp_path / "sine.wav",
    )


@pytest.fixture
def test_mp4(tmp_path: Path) -> Path:
    """1초짜리 320x240 25fps 테스트 영상 + 오디오 MP4."""
    return _make(
        ["-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
        tmp_path / "test.mp4",
    )
