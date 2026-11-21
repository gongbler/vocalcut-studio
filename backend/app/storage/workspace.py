"""작업 폴더(workspace) 관리 담당 = '창고 관리인'.

파일을 어디에, 어떤 이름으로 저장할지는 오직 이 클래스만 결정한다.
다른 코드는 경로를 직접 조립하지 않고 이 클래스에 물어본다.

폴더 구조:
    workspace/
      uploads/<file_id>/source.mp3   ← 업로드 원본 (이름은 항상 source + 확장자)
      uploads/<file_id>/meta.json    ← 원래 파일 이름 등 부가 정보
      temp/                          ← 처리 중 임시 파일
      outputs/<output_id>/result.mp4 ← 편집 결과물 (+ meta.json)
      jobs/<job_id>.json             ← 작업 대기열 기록
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

CHUNK_SIZE = 1024 * 1024  # 1MB씩 나눠서 복사 → 큰 영상도 메모리를 적게 씀

# file_id 는 uuid4().hex 형식(소문자 16진수 32글자)만 허용한다.
# "../../windows" 같은 값으로 다른 폴더에 접근하는 공격(경로 조작)을 막기 위함.
_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class FileTooLargeError(Exception):
    pass


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.uploads = self.root / "uploads"
        self.temp = self.root / "temp"
        self.outputs = self.root / "outputs"
        self.jobs = self.root / "jobs"

    def ensure(self) -> None:
        for d in (self.uploads, self.temp, self.outputs, self.jobs):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- 공통 ----------
    @staticmethod
    def _create_dir(base: Path) -> tuple[str, Path]:
        new_id = uuid.uuid4().hex
        path = base / new_id
        path.mkdir(parents=True)
        return new_id, path

    @staticmethod
    def _existing_dir(base: Path, item_id: str) -> Path | None:
        if not _FILE_ID_RE.fullmatch(item_id):
            return None
        path = base / item_id
        return path if path.is_dir() else None

    # ---------- 업로드 ----------
    def create_upload_dir(self) -> tuple[str, Path]:
        """새 업로드용 폴더를 만들고 (file_id, 폴더 경로)를 돌려준다."""
        return self._create_dir(self.uploads)

    @staticmethod
    def save_stream(src: BinaryIO, dest: Path, max_bytes: int) -> int:
        """src 를 dest 에 1MB씩 복사한다. max_bytes 를 넘으면 중단하고 에러."""
        written = 0
        with open(dest, "wb") as out:
            while chunk := src.read(CHUNK_SIZE):
                written += len(chunk)
                if written > max_bytes:
                    raise FileTooLargeError(f"파일이 너무 큽니다 (최대 {max_bytes // 1024**2}MB)")
                out.write(chunk)
        return written

    def upload_dir(self, file_id: str) -> Path | None:
        """file_id 에 해당하는 폴더. 형식이 틀렸거나 없으면 None."""
        return self._existing_dir(self.uploads, file_id)

    def remove_upload(self, file_id: str) -> None:
        path = self.upload_dir(file_id)
        if path:
            shutil.rmtree(path, ignore_errors=True)

    # ---------- 결과물 ----------
    def create_output_dir(self) -> tuple[str, Path]:
        """새 결과물용 폴더를 만들고 (output_id, 폴더 경로)를 돌려준다."""
        return self._create_dir(self.outputs)

    def output_dir(self, output_id: str) -> Path | None:
        return self._existing_dir(self.outputs, output_id)

    def remove_output(self, output_id: str) -> None:
        path = self.output_dir(output_id)
        if path:
            shutil.rmtree(path, ignore_errors=True)

    # ---------- 메타 정보 ----------
    @staticmethod
    def write_meta(upload_dir: Path, meta: dict) -> None:
        (upload_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def read_meta(upload_dir: Path) -> dict | None:
        meta_path = upload_dir / "meta.json"
        if not meta_path.is_file():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))
