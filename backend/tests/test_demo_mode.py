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
        assert first.json() == {"demo": True}
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
        assert res.json() == {"demo": False}
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
