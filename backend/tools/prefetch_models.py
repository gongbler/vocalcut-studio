"""AI 모델 미리 받기 (Docker 이미지를 만들 때 한 번 실행).

이미지 안에 모델을 넣어 두면, 서버가 켜진 뒤 첫 사용자가 수백 MB 다운로드를 기다리지 않는다.
실행기들(demucs_runner, whisper_runner)과 '같은 폴더 규칙'으로 받아야 나중에 인터넷 없이 찾을 수 있다:
    <MODELS_DIR>/huggingface/hub/...   (Demucs 4.1, faster-whisper 모두)

실행: (backend 폴더에서) python tools/prefetch_models.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 폴더를 import 기준으로

from app.core import config  # noqa: E402


def main() -> int:
    models_dir = config.MODELS_DIR.resolve()
    # 실행기와 똑같이 설정해야 같은 곳에 저장된다 (import 하기 '전에')
    os.environ["HF_HOME"] = str(models_dir / "huggingface")
    os.environ["TORCH_HOME"] = str(models_dir / "torch")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    from demucs.pretrained import get_model
    from faster_whisper.utils import download_model

    print(f"모델 폴더: {models_dir}", flush=True)
    get_model(config.DEMUCS_MODEL)
    print(f"  Demucs {config.DEMUCS_MODEL} OK", flush=True)
    for name in config.WHISPER_MODELS:
        download_model(name)
        print(f"  Whisper {name} OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
