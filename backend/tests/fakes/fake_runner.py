"""테스트용 '가짜 Demucs 실행기'.

진짜 실행기와 똑같은 JSON 줄 규칙으로 말하지만, AI 대신 짧은 무음 WAV 를 만든다.
--mode 로 성공/메모리 부족/비정상 종료/느린 처리 상황을 흉내 낸다.
"""
import argparse
import json
import sys
import time
import wave
from pathlib import Path


def emit(**d):
    print(json.dumps(d), flush=True)


def write_silence(path: Path, seconds: float = 0.5):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00\x00\x00" * int(44100 * seconds))


p = argparse.ArgumentParser()
p.add_argument("--mode", default="ok")
p.add_argument("--input")
p.add_argument("--outdir")
p.add_argument("--models-dir")
p.add_argument("--model")
p.add_argument("--chunk-sec")
p.add_argument("--ffmpeg")
p.add_argument("--tmpdir")
args = p.parse_args()

# 진짜 실행기처럼 임시 폴더를 만들고, 자기 프로세스 번호를 적어 둔다 (취소 테스트용)
import os  # noqa: E402
Path(args.tmpdir).mkdir(parents=True, exist_ok=True)
(Path(args.tmpdir) / "pid.txt").write_text(str(os.getpid()))

print("some warning text that is not json", flush=True)  # 실제로도 섞여 나올 수 있는 잡음
emit(event="stage", name="decode")

if args.mode == "memory":
    emit(event="error", kind="memory", message="메모리가 부족합니다.", peak_mb=3900)
    sys.exit(2)
if args.mode == "crash":
    sys.stderr.write("Fatal: something exploded\n")
    sys.exit(3221225477 % 256)  # 아무 출력 없이 비정상 종료

if args.mode == "silent":
    time.sleep(30)  # 아무 보고 없이 한참 계산하는 상황 (진짜 Demucs의 한 처리 단위가 20초 넘게 걸리듯)

emit(event="stage", name="load_model")
emit(event="stage", name="separate", chunks=4)
steps = 200 if args.mode == "slow" else 4
for i in range(1, steps + 1):
    emit(event="progress", value=i / steps)
    if args.mode == "slow":
        time.sleep(0.05)

out = Path(args.outdir)
out.mkdir(parents=True, exist_ok=True)
write_silence(out / "vocals.wav")
write_silence(out / "instrumental.wav")
emit(event="done", outputs={"vocals": str(out / "vocals.wav"), "instrumental": str(out / "instrumental.wav")},
     elapsed_sec=0.1, peak_mb=12)
