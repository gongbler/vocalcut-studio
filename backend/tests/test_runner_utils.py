"""AI 실행기 공통 도구 테스트."""
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_emit_sends_korean_as_utf8_through_a_pipe():
    """버그 재발 방지: 파이프로 보낼 때 윈도우 기본 인코딩(cp949)이 쓰이면 서버가 한글 줄을 읽지 못했다."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    code = "from app.services.engines.runner_utils import emit; emit(event='segment', text='안녕하세요 ♪')"
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, check=True)
    msg = json.loads(out.stdout.decode("utf-8"))
    assert msg == {"event": "segment", "text": "안녕하세요 ♪"}


def test_peak_memory_is_measured():
    from app.services.engines.runner_utils import peak_memory_mb

    assert peak_memory_mb() > 1  # 0 이나 -1(측정 실패)이 아니어야 한다
