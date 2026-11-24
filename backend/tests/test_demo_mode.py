"""데모 모드 (공개 사이트): 방문자마다 칸막이가 쳐져 있는지 확인한다.

방문자 A 와 B 를 서로 다른 브라우저(쿠키 보관함이 다른 TestClient 2개)로 흉내 낸다.
"""
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from tests.conftest import requires_ffmpeg


@pytest.fixture
def demo(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path / "workspace")
    return tmp_path / "workspace"


@pytest.fixture
def two_visitors(demo):
    # 같은 서버(app)에 브라우저 2개가 접속 → lifespan 은 바깥 client 에서 한 번만 돌린다
    with TestClient(app) as a:
        b = TestClient(app)
        a.get("/api/session")
        b.get("/api/session")
        yield a, b


def upload(client: TestClient, path: Path, name: str = "노래.wav") -> str:
    with open(path, "rb") as f:
        res = client.post("/api/files", files={"file": (name, f)})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_session_gives_a_visitor_cookie_once(demo):
    with TestClient(app) as c:
        first = c.get("/api/session")
        assert first.json()["demo"] is True
        cookie = first.cookies.get(config.VISITOR_COOKIE)
        assert cookie and len(cookie) == 32
        assert "httponly" in first.headers["set-cookie"].lower()
        # 이미 번호표가 있으면 새로 주지 않는다
        assert config.VISITOR_COOKIE not in c.get("/api/session").cookies


def test_forged_cookie_is_replaced(demo):
    with TestClient(app, cookies={config.VISITOR_COOKIE: "../../etc"}) as c:
        res = c.get("/api/session")
        assert res.cookies.get(config.VISITOR_COOKIE) not in (None, "../../etc")


def test_normal_mode_gives_no_cookie(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path / "workspace")
    with TestClient(app) as c:
        res = c.get("/api/session")
        assert res.json() == {"demo": False, "limits": None}
        assert "set-cookie" not in res.headers


@requires_ffmpeg
def test_visitors_cannot_see_open_or_delete_each_others_files(two_visitors, sine_wav, demo):
    a, b = two_visitors
    song = upload(a, sine_wav)

    assert [i["id"] for i in a.get("/api/library").json()] == [song]
    assert b.get("/api/library").json() == []                         # 목록에 안 보임
    assert b.get(f"/api/files/{song}").status_code == 404              # 정보를 못 봄
    assert b.get(f"/api/files/{song}/content").status_code == 404      # 재생·내려받기 못 함
    assert b.delete(f"/api/library/{song}").status_code == 404         # 지우지 못 함
    assert b.get("/api/storage").json()["uploads_bytes"] == 0           # 저장 공간도 각자
    assert a.get(f"/api/files/{song}").status_code == 200              # 주인은 그대로 씀

    # 실제로 방문자별 폴더에 저장되고, 공용 uploads 에는 아무것도 없다
    visitor_dirs = list((demo / "visitors").iterdir())
    assert len(visitor_dirs) == 2
    assert not (demo / "uploads").exists() or not any((demo / "uploads").iterdir())


@requires_ffmpeg
def test_visitors_cannot_see_or_cancel_each_others_jobs(two_visitors, sine_wav):
    a, b = two_visitors
    song = upload(a, sine_wav)
    job = a.post("/api/edits", json={"source_id": song, "output_format": "mp3"}).json()

    assert b.get(f"/api/jobs/{job['id']}").status_code == 404
    assert b.post(f"/api/jobs/{job['id']}/cancel").status_code == 404
    assert a.get(f"/api/jobs/{job['id']}").status_code == 200
    # B 는 A 의 파일로 작업을 주문할 수도 없다
    assert b.post("/api/edits", json={"source_id": song, "output_format": "mp3"}).status_code == 404


@requires_ffmpeg
def test_other_visitors_busy_job_does_not_block_my_delete(two_visitors, sine_wav):
    a, b = two_visitors
    mine = upload(b, sine_wav)
    started, release = threading.Event(), threading.Event()

    def slow(report):
        started.set()
        release.wait(10)
        return {}

    manager = app.state.job_manager
    manager.submit("test", slow, owner=a.cookies.get(config.VISITOR_COOKIE))  # A 의 작업이 돌고 있는 중
    try:
        assert started.wait(5)
        assert b.delete(f"/api/library/{mine}").status_code == 200    # B 는 자기 파일을 지울 수 있다
    finally:
        release.set()


# ------------------------------------------------------------------ 5-2 데모 제한 · 자동 정리

def test_session_describes_the_limits(demo):
    with TestClient(app) as c:
        limits = c.get("/api/session").json()["limits"]
    assert limits == {"upload_mb": 200, "media_minutes": 5, "ai_minutes": 3, "file_ttl_minutes": 60}


@requires_ffmpeg
def test_too_big_upload_is_refused(two_visitors, sine_wav, monkeypatch):
    a, _ = two_visitors
    monkeypatch.setattr(config, "DEMO_MAX_UPLOAD_BYTES", 1024)
    with open(sine_wav, "rb") as f:
        res = a.post("/api/files", files={"file": ("big.wav", f)})
    assert res.status_code == 413
    assert a.get("/api/library").json() == []


@requires_ffmpeg
def test_too_long_upload_is_refused_and_not_kept(two_visitors, sine_wav, monkeypatch):
    a, _ = two_visitors
    monkeypatch.setattr(config, "DEMO_MAX_MEDIA_SEC", 1.0)   # sine_wav 는 2초
    with open(sine_wav, "rb") as f:
        res = a.post("/api/files", files={"file": ("long.wav", f)})
    assert res.status_code == 413
    assert "1초 이하의 파일만" in res.json()["detail"]
    assert a.get("/api/library").json() == []


@requires_ffmpeg
def test_ai_work_on_long_files_is_refused(two_visitors, sine_wav, monkeypatch):
    from app.api.deps import get_separator
    from app.services.engines.base import Availability

    class ReadySeparator:
        name = "fake"

        def availability(self):
            return Availability(ok=True)

    a, _ = two_visitors
    song = upload(a, sine_wav)
    monkeypatch.setattr(config, "DEMO_MAX_AI_SEC", 1.0)
    app.dependency_overrides[get_separator] = lambda: ReadySeparator()
    try:
        res = a.post("/api/separations", json={"source_id": song})
    finally:
        app.dependency_overrides.pop(get_separator, None)
    assert res.status_code == 413
    assert "보컬 분리" in res.json()["detail"]
    # 편집(자르기)은 AI 가 아니라 가벼우므로 그대로 된다 → 짧게 잘라서 다시 시도할 수 있다
    assert a.post("/api/edits", json={"source_id": song, "output_format": "mp3"}).status_code == 202


def test_queue_rules_one_per_visitor_and_a_total_cap(demo, monkeypatch):
    from app.jobs.manager import JobManager

    monkeypatch.setattr(config, "DEMO_MAX_ACTIVE_JOBS", 2)
    manager = JobManager(demo / "jobs")
    release = threading.Event()

    def slow(report):
        release.wait(10)
        return {}

    a, b, c = (manager.for_owner(x * 32) for x in "abc")
    try:
        a.submit("t", slow)
        with pytest.raises(Exception) as busy:
            a.submit("t", slow)                       # 같은 사람 두 번째 → 거절
        assert getattr(busy.value, "status_code", None) == 429
        b.submit("t", slow)                           # 다른 사람은 가능 (전체 2개)
        with pytest.raises(Exception) as full:
            c.submit("t", slow)                       # 전체가 꽉 참 → 거절
        assert "다른 사용자" in str(full.value)
    finally:
        release.set()
        manager.shutdown(wait=True)


def test_cleanup_removes_only_old_files_of_idle_visitors(tmp_path):
    import os

    from app.services.demo_cleanup import cleanup_visitors

    now = 1_000_000.0
    root = tmp_path / "workspace"

    def item(visitor: str, kind: str, name: str, age_min: float) -> Path:
        p = root / "visitors" / visitor / kind / name
        p.mkdir(parents=True)
        (p / "x.bin").write_bytes(b"1")
        os.utime(p, (now - age_min * 60, now - age_min * 60))
        return p

    old = item("a" * 32, "uploads", "old", 90)
    fresh = item("a" * 32, "uploads", "fresh", 10)
    old_out = item("a" * 32, "outputs", "o", 90)
    busy_old = item("b" * 32, "uploads", "busy", 90)
    gone = item("c" * 32, "uploads", "only", 90)
    (root / "visitors" / ("d" * 32)).mkdir()            # 번호표만 받고 아무것도 안 올린 방문자

    r = cleanup_visitors(root, is_busy=lambda v: v == "b" * 32, ttl_sec=3600, now=now)

    assert not old.exists() and not old_out.exists()
    assert fresh.exists()                                # 10분 된 파일은 남김
    assert busy_old.exists()                             # 작업 중인 방문자는 건드리지 않음
    assert not gone.parent.parent.exists()               # 파일이 다 지워진 방문자 폴더는 통째로
    assert not (root / "visitors" / ("d" * 32)).exists() # 빈 방문자 폴더도
    assert r == {"items": 3, "visitors": 2}


@requires_ffmpeg
def test_running_server_deletes_expired_files_by_itself(demo, sine_wav, monkeypatch):
    """서버가 켜져 있는 동안 정리 작업이 스스로 돌아 오래된 파일을 지운다 (시간을 아주 짧게 줄여 확인)."""
    import time

    monkeypatch.setattr(config, "DEMO_FILE_TTL_SEC", 0.5)
    monkeypatch.setattr(config, "DEMO_CLEANUP_INTERVAL_SEC", 0.2)
    with TestClient(app) as c:
        c.get("/api/session")
        song = upload(c, sine_wav)
        assert c.get(f"/api/files/{song}").status_code == 200
        deadline = time.time() + 10
        while time.time() < deadline and c.get("/api/library").json():
            time.sleep(0.2)
        assert c.get("/api/library").json() == []
        assert c.get(f"/api/files/{song}").status_code == 404
