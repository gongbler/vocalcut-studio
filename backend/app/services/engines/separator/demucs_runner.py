"""Demucs 보컬/MR 분리 '실행기' — 서버와 분리된 별도 프로세스로 실행된다.

왜 별도 프로세스인가?
  - PyTorch + AI 모델은 메모리를 많이 쓴다(RAM 4GB PC에서는 특히 위험).
  - 서버 안에서 돌리면, 메모리가 터질 때 서버까지 같이 죽는다.
  - 별도 프로세스로 돌리면 끝나는 순간 메모리를 운영체제에 '전부' 돌려주고,
    실패해도 서버는 멀쩡하다. (서버는 torch 를 import 조차 하지 않는다)

왜 조각(chunk) 처리인가?
  - Demucs 기본 방식은 곡 전체를 메모리에 올려 곡 길이에 비례해 메모리가 늘어난다.
  - 30초 조각씩 처리하고 바로 파일에 쓰면, 곡 길이와 상관없이 메모리가 일정하다.

처리 순서:
  1) FFmpeg로 입력을 44.1kHz 스테레오 float32 '날 데이터' 임시 파일로 변환 (디스크)
  2) 그 파일을 memmap 으로 연다 → 파일 내용을 메모리에 다 올리지 않고 필요한 부분만 읽기
  3) 곡 전체의 평균/표준편차 계산 (소리 크기 표준화용, 조각마다 같은 기준을 써야 이음매가 자연스러움)
  4) 조각마다: 읽기 → 표준화 → Demucs → 원래 크기로 → 겹친 부분 섞기 → WAV에 이어 쓰기

서버와의 대화 방법: 표준출력(stdout)에 JSON 한 줄씩 출력한다.
  {"event": "stage", "name": "separate"}
  {"event": "progress", "value": 0.42}
  {"event": "done", "outputs": {...}, "elapsed_sec": 81.2, "peak_mb": 760}
  {"event": "error", "kind": "memory", "message": "..."}
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from app.services.engines.runner_utils import emit, peak_memory_mb  # 공통 도구

SAMPLE_RATE = 44100  # Demucs 모델이 학습된 샘플레이트
CHANNELS = 2

_progress_state = {"chunk": 0, "chunks": 1}


def emit_progress(inner: float) -> None:
    """전체 진행률 = (끝난 조각 수 + 지금 조각의 진행률) / 전체 조각 수"""
    s = _progress_state
    emit(event="progress", value=round((s["chunk"] + inner) / s["chunks"], 4))


def decode_to_raw(src: Path, dst: Path, ffmpeg: str) -> None:
    """어떤 형식이든 44.1kHz 스테레오 float32 날 데이터 파일로 변환 (메모리가 아니라 디스크에)."""
    cmd = [ffmpeg, "-y", "-nostdin", "-v", "error", "-i", str(src),
           "-vn", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "-f", "f32le", str(dst)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("오디오 변환 실패: " + result.stderr.decode("utf-8", "replace")[-300:])


def global_stats(frames, block: int = SAMPLE_RATE * 30) -> tuple[float, float]:
    """곡 전체 모노 신호의 평균/표준편차를 '조각씩' 계산 (전체를 메모리에 올리지 않음)."""
    import numpy as np

    n, total, total_sq = 0, 0.0, 0.0
    for i in range(0, len(frames), block):
        mono = frames[i : i + block].mean(axis=1, dtype=np.float64)
        n += len(mono)
        total += float(mono.sum())
        total_sq += float((mono * mono).sum())
    mean = total / max(n, 1)
    var = max(total_sq / max(n, 1) - mean * mean, 0.0)
    return mean, var ** 0.5 + 1e-8


def open_wav_writer(path: Path) -> wave.Wave_write:
    w = wave.open(str(path), "wb")
    w.setnchannels(CHANNELS)
    w.setsampwidth(2)  # 16bit
    w.setframerate(SAMPLE_RATE)
    return w


def write_frames(writer: wave.Wave_write, data) -> None:
    """(채널, 프레임) float 배열을 16bit 정수로 바꿔 WAV 에 이어 쓴다."""
    import numpy as np

    pcm = (np.clip(data, -1.0, 1.0).T * 32767).astype("<i2")
    writer.writeframes(pcm.tobytes())


def model_is_cached(models_dir: Path, model: str) -> bool:
    """HuggingFace 캐시 폴더에 모델 파일(safetensors)이 이미 있는지."""
    repo = "HTDemucs" if model == "htdemucs" else (
        "HTDemucs-" + model[len("htdemucs_"):] if model.startswith("htdemucs_") else "Demucs-" + model)
    snapshots = models_dir / "huggingface" / "hub" / f"models--adefossez--{repo}" / "snapshots"
    return snapshots.is_dir() and any(snapshots.rglob("*.safetensors"))


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
                emit_progress(i / total)

    demucs.apply.tqdm = _Hook  # demucs.apply 안에서 쓰는 `tqdm.tqdm(...)` 를 바꿔치기


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--outdir", required=True, type=Path)
    p.add_argument("--models-dir", required=True, type=Path)
    p.add_argument("--model", default="htdemucs")
    p.add_argument("--chunk-sec", type=float, default=30.0, help="한 번에 처리할 조각 길이(초)")
    p.add_argument("--overlap-sec", type=float, default=2.0, help="조각끼리 겹치는 길이(초)")
    p.add_argument("--segment", type=float, default=None, help="Demucs 내부 처리 단위(초)")
    p.add_argument("--threads", type=int, default=0, help="CPU 스레드 수 (0 = 자동)")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--tmpdir", type=Path, default=None,
                   help="임시 파일 위치. 강제 종료돼도 호출한 쪽이 지울 수 있도록 지정한다")
    args = p.parse_args(argv)

    # 모델 파일을 프로젝트 안(models/)에 받도록 지정 — torch/demucs 를 import 하기 '전에' 설정해야 한다
    # Demucs 4.1 은 HuggingFace 에서 받고(HF_HOME), 옛 모델은 torch hub 에서 받는다(TORCH_HOME)
    models_dir = args.models_dir.resolve()
    os.environ["HF_HOME"] = str(models_dir / "huggingface")
    os.environ["TORCH_HOME"] = str(models_dir / "torch")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # 모델을 이미 받아 뒀으면 인터넷에 접속하지 않는다 (오프라인에서도 동작 + 불필요한 외부 접속 없음)
    if model_is_cached(models_dir, args.model):
        os.environ["HF_HUB_OFFLINE"] = "1"
    started = time.monotonic()
    if args.tmpdir:
        args.tmpdir.mkdir(parents=True, exist_ok=True)
        tmp_dir = args.tmpdir
    else:
        tmp_dir = Path(tempfile.mkdtemp(prefix="vocalcut_sep_"))
    writers: list[wave.Wave_write] = []

    try:
        import numpy as np
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        from app.services.engines.separator.chunking import OverlapStitcher, plan_chunks

        if args.threads:
            torch.set_num_threads(args.threads)
        install_progress_hook()

        emit(event="stage", name="decode")
        raw_path = tmp_dir / "input.f32"
        decode_to_raw(args.input, raw_path, args.ffmpeg)
        if raw_path.stat().st_size == 0:
            raise RuntimeError("소리 데이터가 없습니다.")
        # memmap: 파일을 '배열처럼' 다루지만, 실제로 접근한 부분만 메모리에 올라온다
        frames = np.memmap(raw_path, dtype="<f4", mode="r").reshape(-1, CHANNELS)
        mean, std = global_stats(frames)

        emit(event="stage", name="load_model")
        model = get_model(args.model)
        model.cpu().eval()
        names = list(model.sources)  # 예: ["drums", "bass", "other", "vocals"]
        vocal_idx = names.index("vocals")

        args.outdir.mkdir(parents=True, exist_ok=True)
        outputs = {"vocals": args.outdir / "vocals.wav", "instrumental": args.outdir / "instrumental.wav"}
        vocal_writer = open_wav_writer(outputs["vocals"])
        inst_writer = open_wav_writer(outputs["instrumental"])
        writers = [vocal_writer, inst_writer]

        overlap = int(args.overlap_sec * SAMPLE_RATE)
        chunks = plan_chunks(len(frames), int(args.chunk_sec * SAMPLE_RATE), overlap)
        _progress_state["chunks"] = len(chunks)
        vocal_stitch, inst_stitch = OverlapStitcher(overlap), OverlapStitcher(overlap)

        emit(event="stage", name="separate", chunks=len(chunks))
        for chunk in chunks:
            _progress_state["chunk"] = chunk.index
            # 이 조각만 메모리로 복사 → (채널, 프레임) 모양으로
            piece = np.ascontiguousarray(frames[chunk.start : chunk.end].T)
            mix = (torch.from_numpy(piece) - mean) / std
            with torch.inference_mode():  # 학습용 기록을 끄고 추론만 → 메모리 절약
                sources = apply_model(
                    model, mix[None], device="cpu", shifts=0, split=True,
                    overlap=0.25, progress=True, segment=args.segment, num_workers=0,
                )[0]
            sources = (sources * std + mean).numpy()
            vocals = sources[vocal_idx]
            instrumental = sources.sum(axis=0) - vocals  # 보컬을 뺀 나머지 전부 = MR
            last = chunk.index == len(chunks) - 1
            write_frames(vocal_writer, vocal_stitch.push(vocals, last))
            write_frames(inst_writer, inst_stitch.push(instrumental, last))
            del piece, mix, sources, vocals, instrumental  # 다음 조각 전에 메모리 정리
            emit_progress(1.0)

        for w in writers:
            w.close()
        writers = []
        del frames  # memmap 파일 닫기 (윈도우는 열린 파일을 지울 수 없음)

        emit(event="done", outputs={k: str(v) for k, v in outputs.items()},
             elapsed_sec=round(time.monotonic() - started, 1), peak_mb=round(peak_memory_mb()))
        return 0
    except MemoryError:
        emit(event="error", kind="memory", message="메모리가 부족합니다.",
             peak_mb=round(peak_memory_mb()))
        return 2
    except Exception as e:  # noqa: BLE001 — 어떤 에러든 서버가 알아들을 형식으로 전달
        msg = str(e)
        kind = "memory" if "memory" in msg.lower() and "alloc" in msg.lower() else type(e).__name__
        emit(event="error", kind=kind, message=msg[:500], peak_mb=round(peak_memory_mb()))
        return 1
    finally:
        for w in writers:
            w.close()
        import gc
        import shutil
        gc.collect()  # memmap 참조를 확실히 정리한 뒤
        shutil.rmtree(tmp_dir, ignore_errors=True)  # 임시 파일 삭제


if __name__ == "__main__":
    sys.exit(main())
