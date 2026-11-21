"""작업 상태 조회 / 취소 API. 화면이 1초마다 '제 주문 어떻게 됐어요?' 하고 묻는 창구."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_job_manager
from app.jobs.manager import JobManager
from app.schemas.job import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, jobs: JobManager = Depends(get_job_manager)) -> JobOut:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"작업을 찾을 수 없습니다: {job_id}")
    return JobOut.from_job(job)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, jobs: JobManager = Depends(get_job_manager)) -> JobOut:
    """취소 요청. 처리 중인 작업은 몇 초 안에 멈춘다 (상태가 cancelled 가 될 때까지 계속 조회)."""
    job = jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"작업을 찾을 수 없습니다: {job_id}")
    return JobOut.from_job(job)
