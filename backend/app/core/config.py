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
TRANSCRIBER_ENGINE = "whisper"

# AI 모델 저장 폴더 (git 에는 올라가지 않음)
MODELS_DIR = BACKEND_DIR / "models"
DEMUCS_MODEL = "htdemucs"
# 한 번에 처리할 조각 길이(초). 실측: 30초 조각 ≈ 최대 750MB (RAM 4GB PC 기준으로 정함)
DEMUCS_CHUNK_SEC = 30.0

# 자막 받아쓰기 모델 (README 실측표 기준: small = 정확, base = 약 2배 빠르고 메모리 절반)
WHISPER_MODELS = {"small": "정확 (권장)", "base": "빠름"}
WHISPER_DEFAULT_MODEL = "small"
# VAD 가 한 덩어리로 묶는 소리의 최대 길이(초). 실측: 제한이 없으면 small 이 노래 앞부분 가사를 통째로 빠뜨렸다
WHISPER_MAX_SPEECH_SEC = 10.0
# 반주가 섞인 원곡을 받아 적을 때 VAD(목소리 감지) 기준. 기본 0.5 면 반주 위의 노래를 '목소리 아님'으로 버린다.
# 실측(3분 33초 곡): 0.5 → 10줄, 0.2 → 26줄. MR 만 넣으면 0.2 에서도 0줄(없는 가사를 지어내지 않음).
# 분리된 보컬은 반주가 없으므로 기본값(0.5)을 쓴다 → 41줄.
WHISPER_VAD_THRESHOLD_MIXED = 0.2
# 고른 언어와 감지된 언어가 다를 때, 감지 확신도가 이 이상이면 경고한다
# (실측: 영어 노래 0.95 / 목소리 없는 MR 은 엉터리 감지 0.72 → 그 사이로 정함)
LANGUAGE_MISMATCH_PROB = 0.8

# 업로드 허용 확장자 (소문자, 점 포함)
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ALLOWED_EXTS = ALLOWED_VIDEO_EXTS | ALLOWED_AUDIO_EXTS

# 업로드 최대 크기: 2GB
MAX_UPLOAD_BYTES = 2 * 1024**3
