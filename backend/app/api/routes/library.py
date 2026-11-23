"""'내 파일' API: 목록 · 삭제 · 용량."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_engine, get_job_manager, get_workspace
from app.core import config
from app.jobs.manager import JobManager
from app.services import library_service, media_service
from app.services.engines.base import MediaEngine
from app.storage.workspace import Workspace

router = APIRouter(tags=["library"])


class LibraryItemOut(BaseModel):
    id: str
    original_name: str
    kind: str
    duration_sec: float
    created_at: float
    size_bytes: int                      # 묶음 전체 (원곡 + 보컬/MR + 결과물)
    has_subtitles: bool
    stems: dict[str, str] | None         # {"vocals": id, "instrumental": id}
    output_count: int
    derived_count: int


class DeleteOut(BaseModel):
    deleted_files: int
    deleted_outputs: int
    freed_bytes: int


@router.get("/library", response_model=list[LibraryItemOut])
def list_library(ws: Workspace = Depends(get_workspace), engine: MediaEngine = Depends(get_engine)) -> list:
    return [
        LibraryItemOut(**{k: v for k, v in vars(i).items() if k not in ("output_ids", "derived_ids")},
                       output_count=len(i.output_ids), derived_count=len(i.derived_ids))
        for i in library_service.list_library(ws, engine)
    ]


@router.delete("/library/{file_id}", response_model=DeleteOut)
def delete_item(
    file_id: str,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
    jobs: JobManager = Depends(get_job_manager),
) -> DeleteOut:
    """원곡과 그 묶음(보컬/MR · 결과물 · 자막)을 영구 삭제. 되돌릴 수 없다."""
    try:
        r = library_service.delete_item(ws, engine, file_id, busy=jobs.has_active())
    except media_service.MediaNotFoundError:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    except library_service.FileBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return DeleteOut(**vars(r))


@router.get("/storage")
def storage(ws: Workspace = Depends(get_workspace)) -> dict:
    """작업 폴더 용량 (바이트)."""
    return library_service.storage_usage(ws, config.MODELS_DIR)
