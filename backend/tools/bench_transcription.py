r"""자막 받아쓰기 '이 PC에서 돌아가나?' 측정 도구.

입력 파일의 앞부분 N초를 잘라, 모델 크기별로 Whisper 실행기를 돌리며
  - 걸린 시간 (모델 불러오기 / 받아쓰기, 곡 길이 대비 몇 배인지)
  - 실행기 프로세스의 최대 메모리
  - PC 전체에서 남은 메모리의 최저치
  - 받아 적은 글자 (정확도는 사람이 눈으로 비교)
를 측정한다.

사용 (backend 폴더에서):
  .\.venv\Scripts\python.exe tools\bench_transcription.py <노래파일> --seconds 60 --models tiny base small
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from bench_separation import available_memory_mb  # 같은 tools 폴더의 도구 재사용

BACKEND = Path(__file__).resolve().parents[1]


def run_once(clip: Path, model: str, language: str, beam: int, ffmpeg: str) -> dict:
    cmd = [sys.executable, "-m", "app.services.engines.transcriber.whisper_runner",
           "--input", str(clip), "--models-dir", str(BACKEND / "models"), "--model", model,
           "--language", language, "--beam-size", str(beam), "--ffmpeg", ffmpeg]
    lowest_free = [available_memory_mb()]
    stop = threading.Event()

    def watch_memory():
        while not stop.wait(0.5):
            lowest_free[0] = min(lowest_free[0], available_memory_mb())

    watcher = threading.Thread(target=watch_memory, daemon=True)
    watcher.start()
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    last, lines = {}, []
    for raw in proc.stdout:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if msg["event"] == "stage":
            print(f"    · {msg['name']}  ({time.monotonic() - started:.0f}s)", flush=True)
        elif msg["event"] == "segment":
            lines.append(f"[{msg['start']:6.1f} → {msg['end']:6.1f}] {msg['text']}")
        elif msg["event"] in ("done", "error"):
            last = msg
    proc.wait()
    stop.set()
    watcher.join()
    if proc.returncode != 0 and not last:
        last = {"event": "error", "message": proc.stderr.read().decode("utf-8", "replace")[-800:]}
    last["wall_sec"] = round(time.monotonic() - started, 1)
    last["lowest_free_mb"] = round(lowest_free[0])
    last["lines"] = lines
    return last


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 콘솔에서도 한글이 깨지지 않게
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("--start", type=float, default=0, help="자를 위치(초)")
    p.add_argument("--seconds", type=float, default=60)
    p.add_argument("--models", nargs="+", default=["tiny", "base", "small"])
    p.add_argument("--language", default="ko")
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--out", type=Path, default=None, help="결과 JSON 저장 위치")
    args = p.parse_args()

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    clip = Path(tempfile.mkdtemp(prefix="clip_")) / "clip.wav"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", str(args.start), "-i", str(args.input),
                    "-t", str(args.seconds), "-ac", "1", "-ar", "16000", str(clip)], check=True)

    print(f"PC 남은 메모리(시작 전): {available_memory_mb():.0f} MB")
    print(f"입력: {args.input.name} {args.start:g}초부터 {args.seconds:g}초 · 언어 {args.language} · beam {args.beam}\n")
    results = []
    for model in args.models:
        print(f"▶ {model}")
        r = run_once(clip, model, args.language, args.beam, ffmpeg)
        results.append({"model": model, **r})
        if r.get("event") == "done":
            work = r["elapsed_sec"] - r["load_sec"]
            print(f"    ✅ 전체 {r['wall_sec']}s (불러오기 {r['load_sec']}s + 받아쓰기 {work:.1f}s = 곡 길이의 "
                  f"{work / args.seconds:.2f}배) · 최대 메모리 {r['peak_mb']}MB · PC 최저 여유 {r['lowest_free_mb']}MB"
                  f" · 감지 언어 {r['language']}({r['language_probability']})")
        else:
            print(f"    ❌ {r.get('kind', '')} {r.get('message', '')[:300]} · PC 최저 여유 {r['lowest_free_mb']}MB")
        for line in r["lines"]:
            print("      " + line)
        print()

    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(clip.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
