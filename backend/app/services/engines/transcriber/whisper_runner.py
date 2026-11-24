"""faster-whisper 자막 받아쓰기 '실행기' — 서버와 분리된 별도 프로세스로 실행된다.

Demucs 실행기와 같은 이유로 별도 프로세스다:
  AI 모델이 메모리를 많이 쓰므로, 끝나면 운영체제에 메모리를 전부 돌려주고 실패해도 서버는 멀쩡하다.

처리 순서:
  1) FFmpeg로 입력을 16kHz 모노 float32 로 변환 (Whisper 가 학습된 형식)
  2) 모델 불러오기 (처음 한 번만 인터넷에서 받아 backend/models/ 에 저장)
  3) 받아쓰기: 문장(segment)이 하나 나올 때마다 서버에 바로 보낸다 → 진행률 = 문장 끝 시간 / 전체 길이

서버와의 대화 방법 (JSON 한 줄씩):
  {"event": "stage", "name": "load_model"}
  {"event": "segment", "start": 1.2, "end": 3.4, "text": "안녕하세요"}
  {"event": "progress", "value": 0.42}
  {"event": "done", "language": "ko", "elapsed_sec": 30.1, "peak_mb": 480, ...}
  {"event": "error", "kind": "memory", "message": "..."}
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from app.services.engines.runner_utils import emit, peak_memory_mb, pick_device

SAMPLE_RATE = 16000  # Whisper 가 학습된 샘플레이트


def decode_audio(src: Path, ffmpeg: str):
    """어떤 형식이든 16kHz 모노 float32 배열로. (1시간 ≈ 230MB, 3분 ≈ 12MB)"""
    import numpy as np

    cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", str(src),
           "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("오디오 변환 실패: " + result.stderr.decode("utf-8", "replace")[-300:])
    return np.frombuffer(result.stdout, dtype="<f4")


def load_model(name: str, compute_type: str, threads: int):
    """이미 받아 둔 모델이 있으면 인터넷에 접속하지 않고, 없을 때만 받는다."""
    import ctranslate2
    from faster_whisper import WhisperModel

    device = pick_device(lambda: ctranslate2.get_cuda_device_count() > 0)
    if device == "cuda" and compute_type == "int8":
        compute_type = "int8_float16"  # GPU 에서는 int8 + float16 조합이 빠르고 메모리도 적다
    kwargs = dict(device=device, compute_type=compute_type, cpu_threads=threads)
    try:
        return WhisperModel(name, local_files_only=True, **kwargs)
    except Exception:  # noqa: BLE001 — 캐시에 없음
        emit(event="stage", name="download")
        return WhisperModel(name, **kwargs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="faster-whisper 받아쓰기 실행기")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--models-dir", type=Path, required=True)
    p.add_argument("--model", default="small", help="tiny / base / small / medium ...")
    p.add_argument("--language", default="ko", help="'auto' 면 자동 감지")
    p.add_argument("--compute-type", default="int8", help="int8 = 메모리 절약 (CPU 권장)")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--threads", type=int, default=0, help="CPU 스레드 수 (0 = 자동)")
    p.add_argument("--no-vad", action="store_true", help="무음 건너뛰기(VAD) 끄기")
    p.add_argument("--max-speech-sec", type=float, default=None,
                   help="VAD 가 한 덩어리로 묶는 소리의 최대 길이(초). 짧을수록 문장을 덜 빠뜨린다")
    p.add_argument("--vad-threshold", type=float, default=None,
                   help="VAD 가 '목소리'로 볼 확률 기준 (기본 0.5). 반주가 섞인 원곡은 낮춰야 노래를 덜 놓친다")
    p.add_argument("--word-timestamps", action="store_true", help="단어별 시간까지 계산")
    p.add_argument("--ffmpeg", default="ffmpeg")
    args = p.parse_args(argv)

    # 모델을 프로젝트 안(models/huggingface)에 받는다 — Demucs 와 같은 폴더 (import 전에 설정)
    os.environ["HF_HOME"] = str(args.models_dir.resolve() / "huggingface")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    started = time.monotonic()

    try:
        emit(event="stage", name="decode")
        audio = decode_audio(args.input, args.ffmpeg)
        duration = len(audio) / SAMPLE_RATE
        if duration == 0:
            raise RuntimeError("소리 데이터가 없습니다.")

        emit(event="stage", name="load_model")
        model = load_model(args.model, args.compute_type, args.threads)
        load_sec = time.monotonic() - started

        vad_parameters = {k: v for k, v in (("max_speech_duration_s", args.max_speech_sec),
                                            ("threshold", args.vad_threshold)) if v is not None} or None

        # 언어 확인: 사용자가 언어를 골랐어도 '실제로 무슨 언어인지' 따로 들어 본다.
        # 실측: 영어 노래를 '한국어'로 받아 적게 하면 AI 가 39초쯤에서 포기하고 나머지를 통째로 버렸다.
        # → 고른 언어와 다르면 화면에서 경고한다. (목소리 구간만 최대 3조각(=90초) 들어 보고 판단)
        emit(event="stage", name="detect_language")
        try:
            from faster_whisper.vad import VadOptions

            # ⚠️ transcribe() 는 dict 도 받지만 detect_language() 는 VadOptions 객체만 받는다 (dict 면 조용히 실패)
            detected, detected_prob, _ = model.detect_language(
                audio, vad_filter=not args.no_vad, vad_parameters=VadOptions(**(vad_parameters or {})),
                language_detection_segments=3,
            )
        except Exception as e:  # noqa: BLE001 — 목소리가 전혀 없는 파일 등: 감지 실패는 치명적이지 않다
            emit(event="warning", message=f"언어 감지 실패: {e}"[:300])  # 조용히 삼키지 않고 로그에 남긴다
            detected, detected_prob = None, 0.0
        language = detected if args.language == "auto" else args.language

        emit(event="stage", name="transcribe", duration_sec=round(duration, 2))
        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=args.beam_size,
            vad_filter=not args.no_vad,  # 반주만 나오는 구간(간주)을 건너뛴다
            vad_parameters=vad_parameters,
            word_timestamps=args.word_timestamps,
            # 앞 문장을 힌트로 쓰지 않는다: 노래 후렴처럼 반복되는 가사에서
            # 같은 말을 끝없이 되풀이하는 오류(환각 반복)가 크게 줄어든다
            condition_on_previous_text=False,
        )
        count = 0
        for seg in segments:  # 문장이 '하나씩' 만들어진다 (제너레이터)
            text = seg.text.strip()
            if text:
                count += 1
                emit(event="segment", start=round(seg.start, 2), end=round(seg.end, 2), text=text)
            emit(event="progress", value=round(min(seg.end / duration, 1.0), 4))

        emit(event="done", language=info.language, language_probability=round(info.language_probability, 3),
             detected_language=detected, detected_probability=round(float(detected_prob), 3),
             duration_sec=round(duration, 2), segments=count, load_sec=round(load_sec, 1),
             elapsed_sec=round(time.monotonic() - started, 1), peak_mb=round(peak_memory_mb()))
        return 0
    except MemoryError:
        emit(event="error", kind="memory", message="메모리가 부족합니다.", peak_mb=round(peak_memory_mb()))
        return 2
    except Exception as e:  # noqa: BLE001 — 어떤 에러든 서버가 알아들을 형식으로 전달
        msg = str(e)
        low = msg.lower()
        kind = "memory" if ("memory" in low and "alloc" in low) or "bad_alloc" in low else type(e).__name__
        emit(event="error", kind=kind, message=msg[:500], peak_mb=round(peak_memory_mb()))
        return 1


if __name__ == "__main__":
    sys.exit(main())
