"""Demucs 분리 엔진 — 서버 쪽 '조종기'.

이 파일은 torch 를 import 하지 않는다. 실제 AI 처리는 별도 프로세스(demucs_runner)가 하고,
여기서는 그 프로세스를 실행·감시하고 결과(JSON 줄)를 해석하기만 한다.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.core import config
from app.services.engines.base import (
    Availability,
    OnProgress,
    SeparationError,
    SeparatorEngine,
    StemPaths,
)

logger = logging.getLogger(__name__)

SEPARATE_TIMEOUT_SEC = 3 * 60 * 60  # 저사양 PC에서 긴 곡도 끝낼 수 있게 3시간
HEARTBEAT_SEC = 0.5  # 실행기 보고가 없어도 이 간격으로 취소 여부를 확인

# 실행기가 보고하는 단계 이름 → 화면에 보여줄 말
STAGE_LABELS = {
    "decode": "오디오 준비 중",
    "load_model": "AI 모델 불러오는 중",
    "separate": "보컬/MR 분리 중",
}


def kill_process_tree(proc: subprocess.Popen) -> None:
    """프로세스와 그 자식들까지 모두 종료한다.

    윈도우의 가상환경(.venv) python.exe 는 '진짜 파이썬을 대신 실행해 주는 런처'라서,
    proc.kill() 은 런처만 죽이고 실제로 AI 를 돌리는 자식 프로세스는 남는다.
    taskkill /T(=자식까지) /F(=강제) 로 가족 전체를 종료한다.
    """
    if proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class DemucsSeparator(SeparatorEngine):
    name = "demucs"

    def __init__(
        self,
        models_dir: Path = config.MODELS_DIR,
        model: str = config.DEMUCS_MODEL,
        chunk_sec: float = config.DEMUCS_CHUNK_SEC,
        runner_cmd: list[str] | None = None,
    ) -> None:
        self.models_dir = Path(models_dir)
        self.model = model
        self.chunk_sec = chunk_sec
        # 테스트에서는 '가짜 실행기'로 바꿔 끼울 수 있다 (torch 없이 통신 규칙만 검사)
        self.runner_cmd = runner_cmd or [sys.executable, "-m", "app.services.engines.separator.demucs_runner"]

    # ------------------------------------------------------------------
    def availability(self) -> Availability:
        # find_spec: 패키지가 '설치돼 있는지'만 찾는다. 실제로 불러오지 않아서 가볍다.
        for pkg in ("torch", "demucs"):
            if importlib.util.find_spec(pkg) is None:
                return Availability(False, f"'{pkg}' 패키지가 설치되지 않았습니다 (requirements-ai.txt 참고).")
        if shutil.which("ffmpeg") is None:
            return Availability(False, "FFmpeg를 찾을 수 없습니다.")
        return Availability(True)

    # ------------------------------------------------------------------
    def separate(
        self,
        src: Path,
        out_dir: Path,
        on_progress: OnProgress | None = None,
        on_stage: Callable[[str], None] | None = None,
    ) -> StemPaths:
        status = self.availability()
        if not status.ok:
            raise SeparationError(status.reason, status.reason)

        cmd = [
            *self.runner_cmd,
            "--input", str(src),
            "--outdir", str(out_dir),
            # 실행기의 임시 파일도 out_dir 안에 → 호출한 쪽이 out_dir 만 지우면 모두 정리된다
            "--tmpdir", str(Path(out_dir) / "_work"),
            "--models-dir", str(self.models_dir),
            "--model", self.model,
            "--chunk-sec", str(self.chunk_sec),
            "--ffmpeg", shutil.which("ffmpeg") or "ffmpeg",
        ]
        result: dict | None = None
        last_progress = 0.0
        deadline = time.monotonic() + SEPARATE_TIMEOUT_SEC

        with tempfile.TemporaryFile() as err_file:
            # cwd=backend 폴더: 실행기가 `app...` 모듈을 찾을 수 있도록
            proc = subprocess.Popen(cmd, cwd=config.BACKEND_DIR, stdout=subprocess.PIPE, stderr=err_file)
            assert proc.stdout is not None

            # 실행기의 보고를 '받아 적는' 일은 별도 스레드에 맡긴다.
            # 그래야 다음 보고가 20초 뒤에 오더라도, 이쪽은 0.5초마다 취소 요청을 확인할 수 있다.
            lines: queue.Queue[bytes | None] = queue.Queue()

            def pump() -> None:
                for raw_line in proc.stdout:
                    lines.put(raw_line)
                lines.put(None)  # 끝 표시

            threading.Thread(target=pump, daemon=True).start()
            try:
                while True:
                    if time.monotonic() > deadline:
                        raise SeparationError("timeout", "보컬 분리 시간이 초과되었습니다.")
                    try:
                        raw = lines.get(timeout=HEARTBEAT_SEC)
                    except queue.Empty:
                        # 보고가 없는 동안에도 같은 진행률을 다시 알린다 → 취소됐다면 여기서 JobCancelled 발생
                        if on_progress:
                            on_progress(last_progress)
                        continue
                    if raw is None:
                        break
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue  # JSON 이 아닌 줄(경고 메시지 등)은 무시
                    event = msg.get("event")
                    if event == "progress" and on_progress:
                        last_progress = min(float(msg["value"]), 0.99)
                        on_progress(last_progress)
                    elif event == "stage" and on_stage:
                        on_stage(STAGE_LABELS.get(msg.get("name"), msg.get("name")))
                    elif event in ("done", "error"):
                        result = msg
                proc.wait()
            except BaseException:
                # 취소(JobCancelled)나 시간 초과 → 실행기 프로세스를 즉시 종료해 메모리를 돌려받는다
                kill_process_tree(proc)
                raise

            err_file.seek(0)
            stderr_tail = err_file.read().decode("utf-8", "replace")[-1500:]

        if result is None or result.get("event") != "done" or proc.returncode != 0:
            raise self._to_error(result, proc.returncode, stderr_tail)

        logger.info("demucs done: %.1fs, peak %s MB", result.get("elapsed_sec", 0), result.get("peak_mb"))
        if on_progress:
            on_progress(1.0)
        outputs = result["outputs"]
        return StemPaths(vocals=Path(outputs["vocals"]), instrumental=Path(outputs["instrumental"]))

    @staticmethod
    def _to_error(result: dict | None, returncode: int | None, stderr_tail: str) -> SeparationError:
        """실행기의 실패를 '사용자가 이해할 수 있는 문장'으로 바꾼다."""
        detail = json.dumps(result, ensure_ascii=False) if result else f"exit={returncode} {stderr_tail}"
        kind = (result or {}).get("kind")
        # 윈도우에서 메모리가 바닥나 강제 종료되면 종료 코드가 이상한 큰 수로 나온다
        if kind == "memory" or (result is None and returncode not in (0, 1, 2)):
            return SeparationError(detail, "메모리가 부족해 보컬 분리에 실패했습니다. "
                                           "다른 프로그램(브라우저 탭 등)을 닫고 다시 시도하세요.")
        return SeparationError(detail, "보컬 분리 중 오류가 발생했습니다. 서버 로그를 확인하세요.")
