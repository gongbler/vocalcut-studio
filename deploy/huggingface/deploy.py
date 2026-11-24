"""Hugging Face Space 에 데모 사이트 올리기 (CI 가 자동으로 실행, 손으로도 실행 가능).

    HF_TOKEN=hf_... python deploy/huggingface/deploy.py [--wait]

1. git 에 커밋된 파일만 꺼낸다 (git archive) → 내 PC 의 작업 파일·모델·비밀값이 섞일 수 없다.
2. 데모에 필요 없는 것(문서 이미지·CI 설정·윈도우 실행 스크립트)을 빼고, README 를 Space 소개 카드로 바꾼다.
3. Space 에 올린다. 코드에서 지운 파일은 Space 에서도 지운다.
4. --wait: Space 가 다시 만들어져 켜질 때까지 기다린다 (실패하면 종료 코드 1).

필요한 패키지: huggingface_hub (pip install huggingface_hub)
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPACE = "gongbler/vocalcut-studio"
LEAVE_OUT = ["docs", ".github", "scripts", "deploy", "start.cmd", "stop.cmd"]


def stage(dest: Path) -> str:
    """커밋된 파일을 dest 에 펼치고, 올릴 모양으로 정리한다. 커밋 번호를 돌려준다."""
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True,
                             capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        try:
            tar.extractall(dest, filter="data")  # 안전한 풀기 (Python 3.11.4+)
        except TypeError:
            tar.extractall(dest)  # 옛 Python: 내용이 우리 git 커밋이라 안전
    shutil.copy(dest / "deploy" / "huggingface" / "README.md", dest / "README.md")
    for name in LEAVE_OUT:
        path = dest / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    return commit


def wait_until_running(api, timeout: float = 1800) -> str:
    start, last = time.time(), None
    while time.time() - start < timeout:
        stage_name = api.get_space_runtime(SPACE).stage
        if stage_name != last:
            print(f"  {time.time() - start:4.0f}s  {stage_name}", flush=True)
            last = stage_name
        if stage_name == "RUNNING" and time.time() - start > 30:  # 막 올린 직후엔 이전 버전이 RUNNING 일 수 있음
            return stage_name
        if stage_name in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"):
            return stage_name
        time.sleep(15)
    return "TIMEOUT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", action="store_true", help="Space 가 다시 켜질 때까지 기다리기")
    args = parser.parse_args()

    from huggingface_hub import HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        commit = stage(dest)
        files = sum(1 for p in dest.rglob("*") if p.is_file())
        print(f"올릴 파일 {files}개 (GitHub 커밋 {commit}) → {SPACE}", flush=True)
        info = api.upload_folder(
            folder_path=dest, repo_id=SPACE, repo_type="space",
            commit_message=f"Deploy from GitHub {commit}",
            # 코드에서 지운 파일은 Space 에서도 지운다 (.gitattributes 등 Space 기본 파일은 그대로)
            delete_patterns=["backend/**", "frontend/**", "Dockerfile", ".dockerignore", "README.md"],
        )
        print("올림:", getattr(info, "commit_url", info), flush=True)

    if args.wait:
        print("Space 다시 만드는 중…", flush=True)
        result = wait_until_running(api)
        print("결과:", result, flush=True)
        return 0 if result == "RUNNING" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
