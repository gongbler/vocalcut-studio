"""API 응답 '양식'(Pydantic 모델).

내부 데이터(MediaFile)를 그대로 내보내지 않고, 화면에 필요한 것만 골라 정해진 모양으로 보낸다.
(예: 서버 내부 저장 경로는 보내지 않는다)
FastAPI는 이 양식을 보고 /docs 문서도 자동으로 만들어 준다.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.services.media_service import MediaFile


class VideoStreamOut(BaseModel):
    codec: str
    width: int
    height: int
    fps: float | None


class AudioStreamOut(BaseModel):
    codec: str
    sample_rate: int
    channels: int


class PeaksOut(BaseModel):
    duration_sec: float
    peaks_per_sec: float
    values: list[float]  # 0.0(무음) ~ 1.0(최대)


class MediaFileOut(BaseModel):
    id: str
    original_name: str
    kind: str  # "video" | "audio"
    format_name: str
    duration_sec: float
    size_bytes: int
    video: VideoStreamOut | None
    audio: AudioStreamOut | None
    content_url: str  # 미리보기/재생용 주소

    @classmethod
    def from_media(cls, m: MediaFile) -> MediaFileOut:
        i = m.info
        return cls(
            id=m.id,
            original_name=m.original_name,
            kind="video" if i.has_video else "audio",
            format_name=i.format_name,
            duration_sec=i.duration_sec,
            size_bytes=i.size_bytes,
            video=VideoStreamOut(**vars(i.video)) if i.video else None,
            audio=AudioStreamOut(**vars(i.audio)) if i.audio else None,
            content_url=f"/api/files/{m.id}/content",
        )
