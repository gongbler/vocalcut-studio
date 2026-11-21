"""파형(피크) 테스트."""
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_job_manager, get_workspace
from app.jobs.manager import JobManager
from app.main import app
from app.services.engines.media.ffmpeg_engine import FFmpegEngine, _peaks_from_pcm
from app.storage.workspace import Workspace
from tests.conftest import FFMPEG, requires_ffmpeg


# ---------- 순수 계산 (FFmpeg 불필요) ----------

def test_peaks_from_pcm_takes_loudest_per_block():
    from array import array
    pcm = array("h", [0, 100, -16384, 50,     # 묶음1: 가장 큰 크기 = 16384 (음수 쪽)
                      32767, 0, 0, 0]).tobytes()  # 묶음2: 32767
    assert _peaks_from_pcm(pcm, samples_per_peak=4) == [0.5, 1.0]


# ---------- 실제 FFmpeg ----------

@requires_ffmpeg
def test_sine_has_steady_peaks(sine_wav):
    peaks = FFmpegEngine().extract_peaks(sine_wav, peaks_per_sec=50)

    assert peaks.duration_sec == pytest.approx(2.0, abs=0.05)
    assert len(peaks.values) == pytest.approx(100, abs=2)   # 2초 × 50
    assert all(0 <= v <= 1 for v in peaks.values)
    middle = peaks.values[10:90]
    assert max(middle) - min(middle) < 0.02                 # 일정한 크기의 '삐-' 소리


@requires_ffmpeg
def test_fade_in_shows_rising_waveform(tmp_path):
    src = tmp_path / "fade.wav"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=duration=2,afade=t=in:d=2", str(src)], check=True)

    v = FFmpegEngine().extract_peaks(src, peaks_per_sec=10).values
    assert v[1] < v[10] < v[18]                             # 점점 커지는 파형


@requires_ffmpeg
def test_video_uses_its_audio_track(test_mp4):
    peaks = FFmpegEngine().extract_peaks(test_mp4, peaks_per_sec=20)
    assert peaks.duration_sec == pytest.approx(1.0, abs=0.1)
    assert max(peaks.values) > 0.05


# ---------- API + 캐시 ----------

@pytest.fixture
def client(tmp_path: Path):
    ws = Workspace(tmp_path / "workspace")
    ws.ensure()
    jobs = JobManager(ws.jobs)
    app.dependency_overrides[get_workspace] = lambda: ws
    app.dependency_overrides[get_job_manager] = lambda: jobs
    with TestClient(app) as c:
        c.ws = ws
        yield c
    app.dependency_overrides.clear()
    jobs.shutdown()


@requires_ffmpeg
def test_peaks_api_caches_result(client, sine_wav):
    with open(sine_wav, "rb") as f:
        file_id = client.post("/api/files", files={"file": ("a.wav", f)}).json()["id"]
    cache = client.ws.uploads / file_id / "peaks.json"
    assert not cache.exists()

    first = client.get(f"/api/files/{file_id}/peaks")
    assert first.status_code == 200
    assert cache.exists()                                   # 처음 요청 때 저장됨

    t0 = time.perf_counter()
    second = client.get(f"/api/files/{file_id}/peaks")
    assert second.json() == first.json()                    # 두 번째는 저장본 그대로
    assert time.perf_counter() - t0 < 1.0


@requires_ffmpeg
def test_peaks_unknown_file_is_404(client):
    assert client.get("/api/files/" + "0" * 32 + "/peaks").status_code == 404
