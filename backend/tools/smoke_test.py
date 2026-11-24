"""켜져 있는 서버(Docker 상자)를 진짜 사용자처럼 한 바퀴 써 보는 점검 (표준 라이브러리만 사용).

CI 가 Docker 이미지를 만든 뒤 실행한다 → "상자 안에서 AI 까지 정말 돌아가는지" 확인.
    python tools/smoke_test.py http://localhost:7860

확인하는 것: 화면(index.html) · 방문자 번호표 · 서버 상태(FFmpeg·AI·한글 글꼴) ·
            업로드 → 보컬 분리 → 자동 자막 → 다른 방문자에게는 안 보이는지
"""
from __future__ import annotations

import http.cookiejar
import io
import json
import math
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave


def tone_wav(seconds: float = 6.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 330 * i / rate)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


class Visitor:
    """쿠키 보관함을 가진 브라우저 한 개."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body: bytes | None = None, ctype: str = "application/json"):
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={"Content-Type": ctype} if body is not None else {})
        try:
            with self.opener.open(req, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, method: str, path: str, data: dict | None = None):
        status, raw = self.call(method, path, json.dumps(data).encode() if data is not None else None)
        return status, json.loads(raw or b"null")

    def upload(self, name: str, content: bytes) -> str:
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                f"Content-Type: audio/wav\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        status, raw = self.call("POST", "/api/files", body, f"multipart/form-data; boundary={boundary}")
        assert status == 201, (status, raw[:300])
        return json.loads(raw)["id"]

    def wait_job(self, job: dict, timeout: float = 600) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, job = self.json("GET", f"/api/jobs/{job['id']}")
            if job["status"] in ("done", "error", "cancelled"):
                return job
            time.sleep(2)
        raise AssertionError(f"작업이 {timeout}초 안에 끝나지 않음: {job}")


def step(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def main(base: str) -> int:
    a, b = Visitor(base), Visitor(base)

    step("화면(index.html)")
    status, raw = a.call("GET", "/")
    assert status == 200 and b'id="root"' in raw, (status, raw[:200])

    step("방문자 번호표 + 데모 모드")
    _, session = a.json("GET", "/api/session")
    assert session["demo"] is True and session["limits"], session
    b.json("GET", "/api/session")

    step("서버 상태: FFmpeg · AI 분리 · AI 자막 · 한글 글꼴")
    _, health = a.json("GET", "/api/health")
    for key in ("separator", "transcriber"):
        assert health[key]["available"], health[key]
    assert health["ffmpeg"]["available"], health["ffmpeg"]
    assert health["subtitle_font"]["available"], health["subtitle_font"]

    step("업로드")
    song = a.upload("smoke.wav", tone_wav())

    step("보컬 분리 (AI, CPU)")
    started = time.time()
    status, job = a.json("POST", "/api/separations", {"source_id": song})
    assert status == 202, job
    job = a.wait_job(job)
    assert job["status"] == "done", job
    print(f"    {time.time() - started:.0f}초", flush=True)

    step("자동 자막 (AI, base 모델)")
    started = time.time()
    status, job = a.json("POST", "/api/transcriptions", {"file_id": song, "model": "base"})
    assert status == 202, job
    job = a.wait_job(job)
    assert job["status"] == "done", job
    print(f"    {time.time() - started:.0f}초", flush=True)

    step("다른 방문자에게는 안 보임")
    _, library = b.json("GET", "/api/library")
    assert library == [], library
    assert b.call("GET", f"/api/files/{song}")[0] == 404

    step("없는 API 는 JSON 404")
    assert a.call("GET", "/api/does-not-exist")[0] == 404

    print("모든 점검 통과 ✅", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7860"))
