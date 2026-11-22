"""AI 실행기(별도 프로세스)를 실행·감시하는 '조종기' 공통 부품.

Demucs(보컬 분리)와 Whisper(자막) 엔진이 똑같이 쓴다:
  - 실행기를 띄우고, JSON 한 줄씩 오는 보고를 받아 적는다.
  - 보고가 한참 없어도 0.5초마다 on_progress 를 다시 불러 → 취소(JobCancelled) 를 바로 알아챈다.
  - 취소·시간 초과 때는 실행기 프로세스를 '자식까지' 종료해 메모리를 돌려받는다.
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core import config
from app.services.engines.base import OnProgress

HEARTBEAT_SEC = 0.5  # 실행기 보고가 없어도 이 간격으로 취소 여부를 확인


class RunnerTimeout(Exception):
    pass


@dataclass
class RunnerResult:
    final: dict | None  # 마지막 done/error 메시지 (없으면 None = 말없이 죽음)
    returncode: int | None
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.final is not None and self.final.get("event") == "done" and self.returncode == 0


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


def run_runner(
    cmd: list[str],
    timeout_sec: float,
    on_message: Callable[[dict], None] | None = None,
    on_progress: OnProgress | None = None,
) -> RunnerResult:
    """실행기를 끝까지 돌린다. progress 는 on_progress 로, 나머지 메시지는 on_message 로 전달한다."""
    final: dict | None = None
    last_progress = 0.0
    deadline = time.monotonic() + timeout_sec

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
                    raise RunnerTimeout()
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
                    msg = json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue  # JSON 이 아닌 줄(경고 메시지 등)은 무시
                if not isinstance(msg, dict):
                    continue
                event = msg.get("event")
                if event == "progress":
                    last_progress = min(float(msg["value"]), 0.99)
                    if on_progress:
                        on_progress(last_progress)
                    continue
                if event in ("done", "error"):
                    final = msg
                if on_message:
                    on_message(msg)
            proc.wait()
        except BaseException:
            # 취소(JobCancelled)나 시간 초과 → 실행기 프로세스를 즉시 종료해 메모리를 돌려받는다
            kill_process_tree(proc)
            raise

        err_file.seek(0)
        stderr_tail = err_file.read().decode("utf-8", "replace")[-1500:]
    return RunnerResult(final, proc.returncode, stderr_tail)


def is_memory_failure(result: RunnerResult) -> bool:
    """메모리 부족으로 실패했는지. 윈도우에서 메모리가 바닥나 강제 종료되면 종료 코드가 이상한 큰 수로 나온다."""
    kind = (result.final or {}).get("kind")
    return kind == "memory" or (result.final is None and result.returncode not in (0, 1, 2))


def describe(result: RunnerResult) -> str:
    """서버 로그용 자세한 설명."""
    if result.final:
        return json.dumps(result.final, ensure_ascii=False)
    return f"exit={result.returncode} {result.stderr_tail}"
