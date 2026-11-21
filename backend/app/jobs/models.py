"""작업(Job) = '주문 번호표' 한 장."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"    # 대기 중 (앞 작업이 끝나길 기다림)
    RUNNING = "running"  # 처리 중
    DONE = "done"        # 완료
    ERROR = "error"      # 실패

    @property
    def finished(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.ERROR)


@dataclass
class Job:
    id: str
    kind: str                      # 작업 종류: "edit", (2-4부터) "separate", "mix" ...
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0          # 0.0 ~ 1.0
    message: str | None = None     # 화면에 보여줄 현재 단계 설명
    result: dict[str, Any] | None = None  # 완료 시 결과 (예: {"output_id": "..."})
    error: str | None = None       # 실패 시 사용자에게 보여줄 문장
    created_at: float = 0.0
    updated_at: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Job:
        return cls(**{**d, "status": JobStatus(d["status"])})
