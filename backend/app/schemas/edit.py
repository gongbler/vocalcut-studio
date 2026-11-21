"""편집 요청/응답 양식."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.edit_service import EditOutput
from app.services.engines.base import EditSpec


class EditRequest(BaseModel):
    # Field(...) 의 ge/le 는 '기본 형식 검사'. 파일 길이와 비교하는 검사는 서비스에서 한다.
    source_id: str
    start_sec: float = Field(0.0, ge=0)
    end_sec: float | None = Field(None, gt=0)
    volume_db: float = Field(0.0, ge=-30, le=20)
    fade_in_sec: float = Field(0.0, ge=0)
    fade_out_sec: float = Field(0.0, ge=0)
    # Literal: 이 세 값 중 하나만 허용 (그 외 값은 FastAPI가 자동으로 422 에러)
    # None 이면 영상→mp4, 오디오→mp3
    output_format: Literal["mp4", "mp3", "wav"] | None = None

    def to_spec(self) -> EditSpec:
        return EditSpec(
            start_sec=self.start_sec,
            end_sec=self.end_sec,
            volume_db=self.volume_db,
            fade_in_sec=self.fade_in_sec,
            fade_out_sec=self.fade_out_sec,
        )


class EditOutputOut(BaseModel):
    id: str
    source_id: str
    download_name: str
    format: str
    kind: str  # "video" | "audio"
    duration_sec: float
    size_bytes: int
    content_url: str   # 재생용 (브라우저 안에서 열기)
    download_url: str  # 다운로드용 (파일로 저장)

    @classmethod
    def from_output(cls, o: EditOutput) -> EditOutputOut:
        return cls(
            id=o.id,
            source_id=o.source_id,
            download_name=o.download_name,
            format=o.format,
            kind="video" if o.info.has_video else "audio",
            duration_sec=o.info.duration_sec,
            size_bytes=o.info.size_bytes,
            content_url=f"/api/outputs/{o.id}/content",
            download_url=f"/api/outputs/{o.id}/download",
        )
