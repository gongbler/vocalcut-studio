"""Demucs 보컬/MR 분리 '실행기' — 서버와 분리된 별도 프로세스로 실행된다.

왜 별도 프로세스인가?
  - PyTorch + AI 모델은 메모리를 많이 쓴다(RAM 4GB PC에서는 특히 위험).
  - 서버 안에서 돌리면, 메모리가 터질 때 서버까지 같이 죽는다.
  - 별도 프로세스로 돌리면 끝나는 순간 메모리를 운영체제에 '전부' 돌려주고,
    실패해도 서버는 멀쩡하다. (서버는 torch 를 import 조차 하지 않는다)

서버와의 대화 방법: 표준출력(stdout)에 JSON 한 줄씩 출력한다.
  {"event": "progress", "value": 0.42}
  {"event": "done", "outputs": {...}, "elapsed_sec": 81.2, "peak_mb": 1830}
  {"event": "error", "message": "..."}

사용 예:
  python -m app.services.engines.separator.demucs_runner \
      --input song.wav --outdir out/ --models-dir models/ --model htdemucs --segment 7
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

SAMPLE_RATE = 44100  # Demucs 모델이 학습된 샘플레이트


def emit(**data) -> None:
    print(json.dumps(data, ensure_ascii=False), flush=True)


def peak_memory_mb() -> float:
    """이 프로세스가 지금까지 사용한 '최대' 메모리(MB)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        # 함수의 인자/반환 '자료형'을 꼭 알려줘야 한다.
        # 안 그러면 ctypes 가 64비트 핸들을 32비트 정수로 잘라 보내서 호출이 조용히 실패한다 (→ 0MB 로 보임)
        get_current = ctypes.windll.kernel32.GetCurrentProcess
        get_current.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        get_info.restype = wintypes.BOOL

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        if not get_info(get_current(), ctypes.byref(counters), counters.cb):
            return -1.0  # 측정 실패를 0과 구분
        return counters.PeakWorkingSetSize / 1024**2
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB 단위


def decode_audio(path: Path, ffmpeg: str):
    """FFmpeg로 어떤 형식이든 44.1kHz 스테레오 float32 로 풀어서 (2, N) 텐서로 만든다."""
    import numpy as np
    import torch

    cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", str(path),
           "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    samples = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).T.copy()
    return torch.from_numpy(samples)


def save_wav(tensor, path: Path) -> None:
    """(2, N) float 텐서를 16bit WAV 로 저장 (파이썬 내장 wave 모듈 사용)."""
    import numpy as np

    pcm = (tensor.clamp(-1, 1).numpy().T * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def install_progress_hook() -> None:
    """Demucs 내부의 진행 막대(tqdm)를 가로채서 우리 형식의 진행률 줄로 바꾼다."""
    import demucs.apply

    class _Hook:
        @staticmethod
        def tqdm(iterable, **_kwargs):
            items = list(iterable)
            total = max(len(items), 1)
            for i, item in enumerate(items, 1):
                yield item
                emit(event="progress", value=round(i / total, 4))

    demucs.apply.tqdm = _Hook  # demucs.apply 안에서 쓰는 `tqdm.tqdm(...)` 를 바꿔치기


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--outdir", required=True, type=Path)
    p.add_argument("--models-dir", required=True, type=Path)
    p.add_argument("--model", default="htdemucs")
    p.add_argument("--segment", type=float, default=None, help="한 번에 처리할 길이(초). 작을수록 메모리 적게")
    p.add_argument("--threads", type=int, default=0, help="CPU 스레드 수 (0 = 자동)")
    p.add_argument("--ffmpeg", default="ffmpeg")
    args = p.parse_args(argv)

    # 모델 파일을 프로젝트 안(models/)에 받도록 지정 — torch/demucs 를 import 하기 '전에' 설정해야 한다
    # Demucs 4.1 은 HuggingFace 에서 받고(HF_HOME), 옛 모델은 torch hub 에서 받는다(TORCH_HOME)
    models_dir = args.models_dir.resolve()
    os.environ["HF_HOME"] = str(models_dir / "huggingface")
    os.environ["TORCH_HOME"] = str(models_dir / "torch")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    started = time.monotonic()

    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        if args.threads:
            torch.set_num_threads(args.threads)
        install_progress_hook()

        emit(event="stage", name="load_model")
        model = get_model(args.model)
        model.cpu().eval()

        emit(event="stage", name="decode")
        wav = decode_audio(args.input, args.ffmpeg)

        # 소리 크기를 표준화해서 넣고, 결과를 원래 크기로 되돌린다 (Demucs 공식 방식)
        ref = wav.mean(0)
        mean, std = ref.mean(), ref.std() + 1e-8
        wav = (wav - mean) / std

        emit(event="stage", name="separate")
        with torch.inference_mode():  # 학습용 기록을 끄고 추론만 → 메모리 절약
            sources = apply_model(
                model, wav[None], device="cpu", shifts=0, split=True,
                overlap=0.25, progress=True, segment=args.segment, num_workers=0,
            )[0]
        sources = sources * std + mean

        emit(event="stage", name="save")
        args.outdir.mkdir(parents=True, exist_ok=True)
        names = list(model.sources)  # 예: ["drums", "bass", "other", "vocals"]
        vocals = sources[names.index("vocals")]
        instrumental = sources.sum(0) - vocals  # 보컬을 뺀 나머지 전부 = MR
        outputs = {"vocals": args.outdir / "vocals.wav", "instrumental": args.outdir / "instrumental.wav"}
        save_wav(vocals, outputs["vocals"])
        save_wav(instrumental, outputs["instrumental"])

        emit(event="done", outputs={k: str(v) for k, v in outputs.items()},
             elapsed_sec=round(time.monotonic() - started, 1), peak_mb=round(peak_memory_mb()))
        return 0
    except MemoryError:
        emit(event="error", kind="memory", message="메모리가 부족합니다.",
             peak_mb=round(peak_memory_mb()))
        return 2
    except Exception as e:  # noqa: BLE001 — 어떤 에러든 서버가 알아들을 형식으로 전달
        emit(event="error", kind=type(e).__name__, message=str(e)[:500],
             peak_mb=round(peak_memory_mb()))
        return 1


if __name__ == "__main__":
    sys.exit(main())
