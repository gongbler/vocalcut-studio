"""배포용 '한 주소' 화면 제공 (app/web.py) 과 AI 장치 고르기 (runner_utils.pick_device)."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.engines.runner_utils import pick_device
from app.web import mount_frontend


def make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    (dist / "assets" / "app-1a2b.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("비밀", encoding="utf-8")
    return dist


def test_serves_index_assets_and_keeps_api_404_as_json(tmp_path):
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict:
        return {"ok": True}

    assert mount_frontend(app, make_dist(tmp_path))
    c = TestClient(app)
    assert c.get("/api/ping").json() == {"ok": True}                 # API 는 그대로
    home = c.get("/?file=abc")
    assert 'id="root"' in home.text and home.headers["cache-control"] == "no-cache"
    asset = c.get("/assets/app-1a2b.js")
    assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
    assert 'id="root"' in c.get("/some/page").text                    # 모르는 주소 → 화면
    missing = c.get("/api/nope")
    assert missing.status_code == 404 and missing.json()["detail"]    # 없는 API → JSON 404
    assert "비밀" not in c.get("/..%2Fsecret.txt").text                 # dist 밖 파일은 안 줌


def test_no_dist_means_nothing_is_mounted(tmp_path):
    assert not mount_frontend(FastAPI(), tmp_path / "없음")


def test_pick_device():
    def boom() -> bool:
        raise RuntimeError("driver")

    assert pick_device(lambda: True, "cpu") == "cpu"                  # CPU 고정
    assert pick_device(lambda: True, "auto") == "cuda"                # GPU 있으면 GPU
    assert pick_device(lambda: False, "auto") == "cpu"
    assert pick_device(boom, "auto") == "cpu"                         # 확인이 실패해도 CPU 로
    assert pick_device(lambda: False, "cuda") == "cpu"                # 고정했는데 없으면 CPU (안내 출력)


def test_cpu_setting_never_touches_the_gpu_check():
    called = []
    pick_device(lambda: called.append(1) or True, "cpu")
    assert called == []
