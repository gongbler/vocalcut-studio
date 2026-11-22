"""테스트용 '가짜 Whisper 실행기'.

진짜 실행기와 똑같은 JSON 줄 규칙(그리고 같은 emit 함수 = UTF-8)으로 말하지만, AI 대신 정해진 한글 가사를 보낸다.
--mode 로 성공/메모리 부족/비정상 종료/느린 처리 상황을 흉내 낸다.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend 폴더 (app 패키지를 찾기 위해)
from app.services.engines.runner_utils import emit  # noqa: E402

LINES = [(0.5, 2.0, "오늘 밤 창문을 열면"), (2.4, 4.0, "차가운 바람이 불어와 ♪")]

p = argparse.ArgumentParser()
p.add_argument("--mode", default="ok")
p.add_argument("--input")
p.add_argument("--models-dir")
p.add_argument("--model")
p.add_argument("--language")
p.add_argument("--max-speech-sec")
p.add_argument("--ffmpeg")
p.add_argument("--vad-threshold")
args = p.parse_args()

print("some warning text that is not json", flush=True)  # 실제로도 섞여 나올 수 있는 잡음
emit(event="stage", name="decode")
if args.mode == "memory":
    emit(event="error", kind="memory", message="메모리가 부족합니다.", peak_mb=3900)
    sys.exit(2)
if args.mode == "crash":
    sys.stderr.write("Fatal: something exploded\n")
    sys.exit(3221225477 % 256)

emit(event="stage", name="load_model")
emit(event="stage", name="detect_language")
detected = "en" if args.mode == "english" else "ko"  # 'english' 모드: 실제로는 영어 노래
emit(event="stage", name="transcribe", duration_sec=4.0)
if args.mode == "slow":
    for i in range(200):
        emit(event="progress", value=i / 400)
        time.sleep(0.05)
for start, end, text in LINES:
    emit(event="segment", start=start, end=end, text=text)
    emit(event="progress", value=end / 4.0)
emit(event="done", language=detected if args.language == "auto" else args.language, language_probability=1.0,
     detected_language=detected, detected_probability=0.98,
     duration_sec=4.0, segments=len(LINES), load_sec=0.1, elapsed_sec=0.2, peak_mb=12)
