"""보컬 분리 '이 PC에서 돌아가나?' 측정 도구.

입력 파일에서 앞부분 N초를 잘라, 설정(segment)별로 Demucs 실행기를 돌리며
  - 걸린 시간 (곡 길이 대비 몇 배인지)
  - 실행기 프로세스의 최대 메모리
  - PC 전체에서 남은 메모리의 최저치 (다른 프로그램까지 포함)
를 측정한다.

사용 (backend 폴더에서):
  .\.venv\Scripts\python.exe tools\bench_separation.py <노래파일> --seconds 30 --segments 7.8 4
"""
from __future__ import annotations

import argparse
import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def available_memory_mb() -> float:
    """PC 전체에서 지금 남아 있는 메모리(MB). Windows 전용."""
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return stat.ullAvailPhys / 1024**2


def run_once(clip: Path, segment: float | None, model: str, ffmpeg: str) -> dict:
    outdir = Path(tempfile.mkdtemp(prefix="bench_"))
    cmd = [sys.executable, "-m", "app.services.engines.separator.demucs_runner",
           "--input", str(clip), "--outdir", str(outdir),
           "--models-dir", str(BACKEND / "models"), "--model", model, "--ffmpeg", ffmpeg]
    if segment:
        cmd += ["--segment", str(segment)]

    lowest_free = [available_memory_mb()]
    stop = threading.Event()

    def watch_memory():
        while not stop.wait(0.5):
            lowest_free[0] = min(lowest_free[0], available_memory_mb())

    watcher = threading.Thread(target=watch_memory, daemon=True)
    watcher.start()
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    last = {}
    for line in proc.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg["event"] == "stage":
            print(f"    · {msg['name']}  ({time.monotonic() - started:.0f}s)", flush=True)
        elif msg["event"] in ("done", "error"):
            last = msg
    proc.wait()
    stop.set()
    watcher.join()
    if proc.returncode != 0 and not last:
        last = {"event": "error", "message": proc.stderr.read().decode("utf-8", "replace")[-800:]}
    last["wall_sec"] = round(time.monotonic() - started, 1)
    last["lowest_free_mb"] = round(lowest_free[0])
    shutil.rmtree(outdir, ignore_errors=True)
    return last


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--segments", type=float, nargs="+", default=[7.8])
    p.add_argument("--model", default="htdemucs")
    args = p.parse_args()

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    clip = Path(tempfile.mkdtemp(prefix="clip_")) / "clip.wav"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(args.input), "-t", str(args.seconds),
                    "-ac", "2", "-ar", "44100", str(clip)], check=True)

    print(f"PC 남은 메모리(시작 전): {available_memory_mb():.0f} MB")
    print(f"입력: {args.input.name} 앞 {args.seconds:g}초 · 모델 {args.model}\n")
    results = []
    for seg in args.segments:
        print(f"▶ segment={seg}")
        r = run_once(clip, seg, args.model, ffmpeg)
        results.append((seg, r))
        if r.get("event") == "done":
            print(f"    ✅ {r['wall_sec']}s (곡 길이의 {r['wall_sec'] / args.seconds:.1f}배) · "
                  f"최대 메모리 {r['peak_mb']}MB · PC 최저 여유 {r['lowest_free_mb']}MB\n")
        else:
            print(f"    ❌ {r.get('kind', '')} {r.get('message', '')[:300]} · PC 최저 여유 {r['lowest_free_mb']}MB\n")

    print(json.dumps([{"segment": s, **r} for s, r in results], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
