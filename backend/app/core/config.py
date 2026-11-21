"""앱 전체에서 공유하는 설정값.

설정을 한 곳에 모아두면, 나중에 경로나 엔진을 바꿀 때 이 파일만 고치면 된다.
"""
from pathlib import Path

APP_NAME = "VocalCut Studio"
APP_VERSION = "0.1.0"

# backend/ 폴더의 절대 경로 (이 파일 위치 기준으로 계산)
BACKEND_DIR = Path(__file__).resolve().parents[2]

# 업로드/임시/결과 파일이 저장될 작업 폴더 (git에는 올라가지 않음)
WORKSPACE_DIR = BACKEND_DIR / "workspace"

# 사용할 엔진 이름. 엔진을 교체할 때는 이 값만 바꾼다.
MEDIA_ENGINE = "ffmpeg"
SEPARATOR_ENGINE = "demucs"

# AI 모델 저장 폴더 (git 에는 올라가지 않음)
MODELS_DIR = BACKEND_DIR / "models"
DEMUCS_MODEL = "htdemucs"
# 한 번에 처리할 조각 길이(초). 실측: 30초 조각 ≈ 최대 750MB (RAM 4GB PC 기준으로 정함)
DEMUCS_CHUNK_SEC = 30.0

# 업로드 허용 확장자 (소문자, 점 포함)
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ALLOWED_EXTS = ALLOWED_VIDEO_EXTS | ALLOWED_AUDIO_EXTS

# 업로드 최대 크기: 2GB
MAX_UPLOAD_BYTES = 2 * 1024**3
