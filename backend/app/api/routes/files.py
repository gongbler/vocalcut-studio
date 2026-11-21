"""파일 업로드/조회 API = '홀 직원(창구)'.

요청을 받아 서비스에 넘기고, 결과나 에러를 HTTP 응답으로 바꿔줄 뿐 직접 요리하지 않는다.

※ 함수들을 `async def` 가 아닌 그냥 `def` 로 만든 이유:
   파일 복사·ffprobe 실행은 시간이 걸리는 '막히는(blocking)' 작업이다.
   일반 def 로 두면 FastAPI가 별도 작업자 스레드에서 실행해 주므로,
   업로드를 처리하는 동안에도 서버가 다른 요청(예: /api/health)에 응답할 수 있다.
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_engine, get_workspace
from app.schemas.media import MediaFileOut, PeaksOut
from app.services import media_service
from app.services.engines.base import EngineNotAvailableError, MediaEngine, MediaProbeError
from app.storage.workspace import FileTooLargeError, Workspace

router = APIRouter(prefix="/files", tags=["files"])


@router.post("", response_model=MediaFileOut, status_code=201)
def upload_file(
    file: UploadFile = File(...),
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> MediaFileOut:
    try:
        media = media_service.import_upload(ws, engine, file.filename or "", file.file)
    except media_service.UnsupportedFileError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except MediaProbeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except EngineNotAvailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return MediaFileOut.from_media(media)


@router.get("/{file_id}", response_model=MediaFileOut)
def get_file(
    file_id: str,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> MediaFileOut:
    try:
        media = media_service.get_media(ws, engine, file_id)
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return MediaFileOut.from_media(media)


@router.get("/{file_id}/peaks", response_model=PeaksOut)
def get_file_peaks(
    file_id: str,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> PeaksOut:
    """파형 그리기용 요약 데이터. 브라우저가 노래 전체를 해석하지 않아도 되게 서버가 미리 계산한다."""
    try:
        peaks = media_service.get_peaks(ws, engine, file_id)
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MediaProbeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return PeaksOut(duration_sec=peaks.duration_sec, peaks_per_sec=peaks.peaks_per_sec, values=peaks.values)


@router.get("/{file_id}/content")
def get_file_content(
    file_id: str,
    ws: Workspace = Depends(get_workspace),
    engine: MediaEngine = Depends(get_engine),
) -> FileResponse:
    """원본 파일을 그대로 보내준다. 브라우저의 <audio>/<video> 재생용.

    FileResponse 는 Range 요청(“30초 지점부터 보내줘”)을 지원해서 재생 바를 움직여도 된다.
    """
    try:
        media = media_service.get_media(ws, engine, file_id)
    except media_service.MediaNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(media.path, filename=media.original_name, content_disposition_type="inline")
