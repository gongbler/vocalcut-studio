"""'내 파일' 담당 = 창고 정리 담당.

- 목록: 사용자가 올린 파일(원곡)마다, 거기서 만들어진 것(분리된 보컬/MR, 결과물, 자막)을 한 묶음으로 보여준다.
- 삭제: 원곡을 지우면 그 묶음을 '통째로' 지운다 (보컬만 남아 주인 없는 파일이 되지 않게).
- 용량: 작업 폴더가 얼마나 차 있는지.
- 서버 시작 정리: 끝나지 못한 작업이 남긴 임시 폴더, 오래된 작업 기록만 지운다.
  ⚠️ 사용자 파일(업로드·결과물)은 절대 자동으로 지우지 않는다. 삭제는 사용자가 눌렀을 때만.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.services.engines.base import MediaEngine, MediaProbeError
from app.services.separation_service import remove_dir_with_retry
from app.storage.workspace import Workspace

logger = logging.getLogger(__name__)

JOB_RECORD_KEEP_DAYS = 30


class FileBusyError(Exception):
    """작업이 진행 중이라 지금은 지울 수 없음."""


def folder_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass  # 그 사이 지워진 파일
    return total


# ---------------------------------------------------------------- 목록

@dataclass
class LibraryItem:
    id: str
    original_name: str
    kind: str                     # "video" | "audio"
    duration_sec: float
    created_at: float
    size_bytes: int               # 이 묶음 전체 (원곡 + 보컬/MR + 결과물)
    has_subtitles: bool
    stems: dict[str, str] | None  # {"vocals": id, "instrumental": id}
    output_ids: list[str] = field(default_factory=list)
    derived_ids: list[str] = field(default_factory=list)  # 이 원곡에서 만들어진 업로드(보컬·MR)


def _basic_info(ws: Workspace, engine: MediaEngine, file_id: str, meta: dict) -> tuple[str, float]:
    """(종류, 길이). 목록을 열 때마다 파일 수십 개를 분석하면 느리므로 meta.json 에 한 번 적어 둔다."""
    if "kind" in meta and "duration_sec" in meta:
        return meta["kind"], float(meta["duration_sec"])
    upload_dir = ws.upload_dir(file_id)
    assert upload_dir is not None
    try:
        info = engine.probe(upload_dir / meta["stored_name"])
        kind, duration = ("video" if info.has_video else "audio"), info.duration_sec
    except MediaProbeError:
        return "audio", 0.0  # 손상된 파일도 목록에는 보여서 지울 수 있게
    ws.write_meta(upload_dir, {**meta, "kind": kind, "duration_sec": duration})
    return kind, duration


def _created_at(path: Path, meta: dict) -> float:
    return float(meta.get("created_at") or path.stat().st_ctime)  # 윈도우: ctime = 만든 시각


def list_library(ws: Workspace, engine: MediaEngine) -> list[LibraryItem]:
    metas: dict[str, dict] = {}
    for d in ws.uploads.iterdir() if ws.uploads.is_dir() else []:
        meta = ws.read_meta(d) if d.is_dir() else None
        if meta and ws.upload_dir(d.name):
            metas[d.name] = meta

    # 원곡 = 다른 파일에서 만들어지지 않은 파일 (원곡이 지워져 주인 없는 보컬/MR 은 스스로 원곡 취급)
    def root_of(file_id: str) -> str:
        parent = metas[file_id].get("derived_from")
        return parent if parent in metas else file_id

    items: dict[str, LibraryItem] = {}
    for file_id, meta in metas.items():
        if root_of(file_id) != file_id:
            continue
        kind, duration = _basic_info(ws, engine, file_id, meta)
        upload_dir = ws.uploads / file_id
        items[file_id] = LibraryItem(
            id=file_id, original_name=meta["original_name"], kind=kind, duration_sec=duration,
            created_at=_created_at(upload_dir, meta), size_bytes=folder_size(upload_dir),
            has_subtitles=(upload_dir / "subtitles.json").is_file(),
            stems=meta.get("stems") if all(i in metas for i in (meta.get("stems") or {}).values()) else None,
        )
    for file_id in metas:
        root = root_of(file_id)
        if root != file_id:
            items[root].derived_ids.append(file_id)
            items[root].size_bytes += folder_size(ws.uploads / file_id)

    # 결과물은 meta 의 source_id 로 주인을 찾는다 (보컬로 만든 결과물은 그 원곡 묶음으로)
    for d in ws.outputs.iterdir() if ws.outputs.is_dir() else []:
        meta = ws.read_meta(d) if d.is_dir() else None
        source = (meta or {}).get("source_id")
        if source in metas:
            item = items[root_of(source)]
            item.output_ids.append(d.name)
            item.size_bytes += folder_size(d)

    return sorted(items.values(), key=lambda i: i.created_at, reverse=True)  # 최근 것부터


# ---------------------------------------------------------------- 삭제

@dataclass(frozen=True)
class DeleteResult:
    deleted_files: int
    deleted_outputs: int
    freed_bytes: int


def delete_item(ws: Workspace, engine: MediaEngine, file_id: str, busy: bool) -> DeleteResult:
    """원곡과 그 묶음(보컬/MR · 결과물 · 자막)을 모두 지운다. 되돌릴 수 없다.

    busy: 지금 처리 중이거나 대기 중인 작업이 있는지. 작업이 쓰고 있는 파일을 지우면
          작업이 이상하게 실패하므로, 작업이 모두 끝난 뒤에만 지운다.
    """
    if ws.upload_dir(file_id) is None:
        from app.services.media_service import MediaNotFoundError
        raise MediaNotFoundError(f"파일을 찾을 수 없습니다: {file_id}")
    if busy:
        raise FileBusyError("처리 중인 작업이 있어요. 작업이 끝난 뒤(또는 취소한 뒤) 삭제하세요.")

    item = next((i for i in list_library(ws, engine) if i.id == file_id), None)
    upload_ids = [file_id, *(item.derived_ids if item else [])]
    output_ids = item.output_ids if item else []
    freed = item.size_bytes if item else folder_size(ws.uploads / file_id)

    # 윈도우는 다른 프로그램(플레이어 등)이 열고 있는 파일을 지우지 못한다 → 몇 번 다시 시도하고,
    # 그래도 남으면 '삭제 완료'라고 거짓말하지 않고 알려준다.
    leftovers = []
    for folder in [ws.outputs / o for o in output_ids] + [ws.uploads / u for u in upload_ids]:
        remove_dir_with_retry(folder)
        if folder.exists():
            leftovers.append(folder.name)
    if leftovers:
        raise FileBusyError("일부 파일을 지우지 못했어요. 그 파일을 재생 중인 플레이어나 프로그램을 닫고 다시 삭제하세요.")
    logger.info("deleted %s: %d uploads, %d outputs, %d bytes", file_id, len(upload_ids), len(output_ids), freed)
    return DeleteResult(deleted_files=len(upload_ids), deleted_outputs=len(output_ids), freed_bytes=freed)


# ---------------------------------------------------------------- 용량

def storage_usage(ws: Workspace, models_dir: Path) -> dict:
    parts = {
        "uploads_bytes": folder_size(ws.uploads),
        "outputs_bytes": folder_size(ws.outputs),
        "temp_bytes": folder_size(ws.temp),
        "jobs_bytes": folder_size(ws.jobs),
    }
    free = shutil.disk_usage(ws.root).free
    return {
        **parts,
        "workspace_bytes": sum(parts.values()),
        "models_bytes": folder_size(models_dir) if models_dir.is_dir() else 0,
        "disk_free_bytes": free,
    }


# ---------------------------------------------------------------- 서버 시작 정리

def startup_cleanup(ws: Workspace, now: float | None = None, keep_days: int = JOB_RECORD_KEEP_DAYS) -> dict:
    """서버가 켜질 때 '안전한 것만' 정리한다.

    - temp/ 안의 모든 것: 서버가 켜지는 순간에는 돌고 있는 작업이 없으므로, 남아 있는 건
      강제 종료(전원 끔·창 닫기)로 끝나지 못한 작업의 찌꺼기다. (분리 1번에 수백 MB)
    - jobs/ 의 끝난 작업 기록 중 keep_days 일이 지난 것.
    - 사용자 파일(uploads/·outputs/)은 건드리지 않는다.
    """
    now = time.time() if now is None else now
    removed_temp, removed_jobs, freed = 0, 0, 0
    for entry in ws.temp.iterdir() if ws.temp.is_dir() else []:
        size = folder_size(entry) if entry.is_dir() else entry.stat().st_size
        try:
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
            removed_temp += 1
            freed += size
        except OSError:
            logger.warning("could not remove temp entry: %s", entry)

    cutoff = now - keep_days * 86400
    for path in ws.jobs.glob("*.json") if ws.jobs.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        finished = data.get("status") in ("done", "error", "cancelled")
        if finished and float(data.get("updated_at", now)) < cutoff:
            path.unlink(missing_ok=True)
            removed_jobs += 1
    result = {"temp_entries": removed_temp, "temp_bytes": freed, "job_records": removed_jobs}
    if removed_temp or removed_jobs:
        logger.info("startup cleanup: %s", result)
    return result
