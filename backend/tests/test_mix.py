"""믹서 테스트 — '파일이 생겼다'가 아니라 싱크·볼륨·EQ·리미터 효과를 실제로 '측정'해서 확인한다."""
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_job_manager, get_workspace
from app.jobs.manager import JobManager
from app.main import app
from app.services import media_service
from app.services.engines.base import MixSpec, MixTrack
from app.services.engines.media.ffmpeg_engine import FFmpegEngine, build_mix_command
from app.storage.workspace import Workspace
from tests.conftest import FFMPEG, requires_ffmpeg
from tests.test_edit_render import max_volume_db


def tone(path: Path, freq: int = 440, sec: float = 2.0, amp: float = 0.5, lead_silence: float = 0.0) -> Path:
    """진폭 amp(0~1)의 freq Hz '삐-' 소리. lead_silence 초만큼 앞에 무음을 붙일 수 있다.

    (FFmpeg 의 sine 소스는 진폭이 1/8로 고정이라, 정확한 크기를 지정할 수 있는 aevalsrc 수식을 쓴다)
    """
    expr = f"if(gte(t\\,{lead_silence})\\,{amp}*sin(2*PI*{freq}*t)\\,0)"
    src = f"aevalsrc={expr}:s=44100:d={sec + lead_silence}"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", src, "-ac", "2", str(path)], check=True)
    return path


def track(path: Path, **kw) -> MixTrack:
    return MixTrack(path=path, duration_sec=FFmpegEngine().probe(path).duration_sec, **kw)


def render(tmp_path: Path, *tracks: MixTrack, name="mix.wav", **spec_kw) -> Path:
    out = tmp_path / name
    FFmpegEngine().render_mix(out, MixSpec(tracks=tracks, **spec_kw))
    return out


SILENT = -60  # 이보다 작으면 '무음'으로 본다


# ---------- 명령어 조립 (FFmpeg 실행 없이) ----------

def test_command_contains_expected_filters(tmp_path):
    a = MixTrack(path=Path("v.wav"), duration_sec=10, offset_sec=0.5, eq_low_db=-6, volume_db=3)
    b = MixTrack(path=Path("m.wav"), duration_sec=10, offset_sec=-0.3, eq_high_db=4)
    cmd = build_mix_command("ffmpeg", Path("out.mp3"), MixSpec(tracks=(a, b)))
    graph = cmd[cmd.index("-filter_complex") + 1]

    assert "adelay=500:all=1" in graph                  # +0.5초 밀기
    assert "atrim=start=0.300" in graph                 # -0.3초 당기기
    assert "bass=g=-6" in graph and "treble=g=4" in graph
    assert "volume=3dB" in graph
    assert "amix=inputs=2:duration=longest:normalize=0" in graph
    assert "alimiter" in graph


# ---------- 실제 렌더링 + 측정 ----------

@requires_ffmpeg
def test_positive_offset_delays_track(tmp_path):
    a = tone(tmp_path / "a.wav", sec=2)
    out = render(tmp_path, track(a, offset_sec=1.0))

    assert FFmpegEngine().probe(out).duration_sec == pytest.approx(3.0, abs=0.05)
    assert max_volume_db(out, 0.0, 0.9) < SILENT        # 처음 1초는 조용
    assert max_volume_db(out, 1.1, 0.5) > -10           # 1초 뒤부터 소리


@requires_ffmpeg
def test_negative_offset_pulls_track_earlier(tmp_path):
    a = tone(tmp_path / "a.wav", sec=2, lead_silence=1.0)  # 1초 무음 + 2초 소리
    out = render(tmp_path, track(a, offset_sec=-1.0))

    assert FFmpegEngine().probe(out).duration_sec == pytest.approx(2.0, abs=0.05)
    assert max_volume_db(out, 0.0, 0.3) > -10           # 무음을 잘라내 바로 소리가 남


@requires_ffmpeg
def test_volume_minus_6db(tmp_path):
    a = tone(tmp_path / "a.wav", amp=0.5)
    out = render(tmp_path, track(a, volume_db=-6))
    assert max_volume_db(out) == pytest.approx(max_volume_db(a) - 6, abs=0.3)


def steady_db(path: Path) -> float:
    """EQ 필터는 소리가 시작되는 순간 짧게 '출렁(과도 응답)'인다 → 0.3초 이후의 안정된 크기만 잰다."""
    return max_volume_db(path, start=0.3)


@pytest.mark.parametrize("freq, field, gain, expected", [
    (40, "eq_low_db", -12, -12),     # 저음 줄이기 → 40Hz(기준 100Hz보다 충분히 낮음)가 거의 12dB 작아짐
    (1000, "eq_mid_db", -6, -6),     # 중음 줄이기 → 1kHz(정중앙)가 정확히 6dB 작아짐
    (16000, "eq_high_db", 6, 6),     # 고음 키우기 → 16kHz(기준 8kHz보다 충분히 높음)가 거의 6dB 커짐
])
@requires_ffmpeg
def test_eq_bands_affect_their_frequency(tmp_path, freq, field, gain, expected):
    a = tone(tmp_path / "a.wav", freq=freq, amp=0.25)
    out = render(tmp_path, track(a, **{field: gain}), limiter=False)
    assert steady_db(out) - steady_db(a) == pytest.approx(expected, abs=1.5)


@requires_ffmpeg
def test_eq_low_does_not_touch_voice_range(tmp_path):
    """저음을 줄여도 목소리 대역(1kHz)은 거의 그대로여야 한다."""
    a = tone(tmp_path / "a.wav", freq=1000, amp=0.25)
    out = render(tmp_path, track(a, eq_low_db=-12), limiter=False)
    assert steady_db(out) == pytest.approx(steady_db(a), abs=0.5)


@requires_ffmpeg
def test_limiter_prevents_clipping_when_tracks_add_up(tmp_path):
    a = tone(tmp_path / "a.wav", amp=0.8)
    b = tone(tmp_path / "b.wav", amp=0.8)

    no_limit = render(tmp_path, track(a), track(b), name="nl.wav", limiter=False)
    limited = render(tmp_path, track(a), track(b), name="l.wav")

    assert max_volume_db(no_limit) > -0.1               # 0.8+0.8 → 1.0 넘어 잘림(클리핑)
    assert max_volume_db(limited) <= -0.8               # 리미터가 -1dB 부근으로 눌러 줌


@requires_ffmpeg
def test_range_and_fades_for_preview(tmp_path):
    a = tone(tmp_path / "a.wav", sec=4)
    out = render(tmp_path, track(a), start_sec=1.0, end_sec=3.0, fade_in_sec=0.5)

    assert FFmpegEngine().probe(out).duration_sec == pytest.approx(2.0, abs=0.05)
    assert max_volume_db(out, 0, 0.03) < max_volume_db(out, 1.0, 0.3) - 10


@requires_ffmpeg
def test_mix_length_is_longest_track_including_offset(tmp_path):
    a = tone(tmp_path / "a.wav", sec=2)
    b = tone(tmp_path / "b.wav", sec=1, freq=660)
    out = render(tmp_path, track(a), track(b, offset_sec=2.5))
    assert FFmpegEngine().probe(out).duration_sec == pytest.approx(3.5, abs=0.05)


# ---------- API ----------

@pytest.fixture
def client(tmp_path):
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


def upload(client, path: Path, name: str) -> str:
    with open(path, "rb") as f:
        return client.post("/api/files", files={"file": (name, f)}).json()["id"]


def mix(client, **payload) -> dict:
    res = client.post("/api/mixes", json=payload)
    assert res.status_code == 202, res.text
    end = time.monotonic() + 60
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{res.json()['id']}").json()
        if job["status"] in ("done", "error"):
            assert job["status"] == "done", job
            return client.get(f"/api/outputs/{job['result']['output_id']}").json()
        time.sleep(0.1)
    raise TimeoutError


@requires_ffmpeg
def test_api_mix_uses_song_name_and_skips_muted(client, tmp_path):
    from app.api.deps import get_engine
    song = upload(client, tone(tmp_path / "s.wav", sec=3), "내 커버곡.wav")
    # 분리 결과처럼 '원곡에서 나온 MR' 을 등록
    mr = media_service.register_file(client.ws, get_engine(), tone(tmp_path / "mr.wav", sec=3, freq=220),
                                     "내 커버곡 (MR).wav", {"derived_from": song, "stem": "instrumental"}).id
    my_voice = upload(client, tone(tmp_path / "me.wav", sec=5, freq=880), "녹음.wav")

    out = mix(client, tracks=[
        {"file_id": mr},
        {"file_id": my_voice, "offset_sec": 0.2},
        {"file_id": song, "muted": True},
    ])
    assert out["download_name"] == "내 커버곡_mix.mp3"   # 분리 트랙이면 원곡 이름 사용
    assert out["duration_sec"] == pytest.approx(5.2, abs=0.1)  # 가장 긴 트랙(5초) + 0.2초 밀기


@requires_ffmpeg
def test_api_rejects_bad_requests(client, tmp_path):
    a = upload(client, tone(tmp_path / "a.wav", sec=40), "a.wav")
    bad = [
        {"tracks": [{"file_id": a, "muted": True}]},                       # 전부 음소거
        {"tracks": [{"file_id": a}], "preview": True},                     # 미리듣기 40초 > 30초
        {"tracks": [{"file_id": a, "volume_db": 50}]},                     # 볼륨 범위 밖
        {"tracks": [{"file_id": a, "offset_sec": -45}]},                   # 길이보다 많이 당김 / 범위 밖
        {"tracks": [{"file_id": a}], "start_sec": 10, "end_sec": 5},        # 구간 거꾸로
    ]
    for payload in bad:
        assert client.post("/api/mixes", json=payload).status_code == 422, payload
    assert client.post("/api/mixes", json={"tracks": [{"file_id": "0" * 32}]}).status_code == 404
    assert list(client.ws.jobs.iterdir()) == []                            # 번호표 발급 안 됨
