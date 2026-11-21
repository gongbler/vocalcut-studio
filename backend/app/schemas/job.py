from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.jobs.models import Job


class JobOut(BaseModel):
    id: str
    kind: str
    status: str          # queued | running | done | error
    progress: float      # 0.0 ~ 1.0
    message: str | None
    error: str | None
    result: dict[str, Any] | None

    @classmethod
    def from_job(cls, j: Job) -> JobOut:
        return cls(
            id=j.id, kind=j.kind, status=j.status.value, progress=round(j.progress, 3),
            message=j.message, error=j.error, result=j.result,
        )
