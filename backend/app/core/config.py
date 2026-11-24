"""앱 전체에서 공유하는 설정값.

설정을 한 곳에 모아두면, 나중에 경로나 엔진을 바꿀 때 이 파일만 고치면 된다.
"""
import os
from pathlib import Path

APP_NAME = "VocalCut Studio"
APP_VERSION = "0.1.0"

# backend/ 폴더의 절대 경로 (이 파일 위치 기준으로 계산)
BACKEND_DIR = Path(__file__).resolve().parents[2]

# 업로드/임시/결과 파일이 저장될 작업 폴더 (git에는 올라가지 않음)
# VOCALCUT_WORKSPACE 로 바꿀 수 있다 (서버·Docker 에서는 쓰기 가능한 폴더를 지정)
WORKSPACE_DIR = Path(os.environ.get("VOCALCUT_WORKSPACE") or BACKEND_DIR / "workspace")

# 데모 모드 (여러 사람이 쓰는 공개 사이트용). VOCALCUT_DEMO=1 일 때만 켜진다.
# 켜지면 방문자마다 보이지 않는 번호표(쿠키)를 주고, 방문자별 작업 폴더를 따로 쓴다.
DEMO_MODE = os.environ.get("VOCALCUT_DEMO") == "1"
VISITOR_COOKIE = "vocalcut_visitor"
VISITOR_COOKIE_MAX_AGE = 7 * 24 * 3600
# 다른 사이트 안에(iframe) 넣어 보여줄 때(예: huggingface.co 페이지) 쿠키가 막히지 않게 하는 설정.
# HTTPS 에서만 동작하므로 서버 배포 때만 켠다 (VOCALCUT_COOKIE_CROSS_SITE=1)
COOKIE_CROSS_SITE = os.environ.get("VOCALCUT_COOKIE_CROSS_SITE") == "1"


def _env_num(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


# 데모 제한 (무료 공용 서버를 지키는 규칙, app/core/demo_limits.py). 더 큰 서버로 옮기면 숫자만 키운다.
DEMO_MAX_UPLOAD_BYTES = int(_env_num("VOCALCUT_DEMO_MAX_UPLOAD_MB", 200) * 1024**2)
DEMO_MAX_MEDIA_SEC = _env_num("VOCALCUT_DEMO_MAX_MEDIA_SEC", 5 * 60)      # 올릴 수 있는 파일 길이
DEMO_MAX_AI_SEC = _env_num("VOCALCUT_DEMO_MAX_AI_SEC", 3 * 60)            # 보컬 분리·자막을 할 수 있는 길이
DEMO_MAX_ACTIVE_JOBS = int(_env_num("VOCALCUT_DEMO_MAX_ACTIVE_JOBS", 3))  # 서버 전체 대기+처리 중 작업 수
DEMO_FILE_TTL_SEC = _env_num("VOCALCUT_DEMO_FILE_TTL_MIN", 60) * 60       # 올린 파일 보관 시간
DEMO_CLEANUP_INTERVAL_SEC = _env_num("VOCALCUT_DEMO_CLEANUP_INTERVAL_SEC", 600)

# 사용할 엔진 이름. 엔진을 교체할 때는 이 값만 바꾼다.
MEDIA_ENGINE = "ffmpeg"
SEPARATOR_ENGINE = "demucs"
TRANSCRIBER_ENGINE = "whisper"

# AI 모델 저장 폴더 (git 에는 올라가지 않음). Docker 에서는 이미지 안에 미리 받아 둔 폴더를 지정한다
MODELS_DIR = Path(os.environ.get("VOCALCUT_MODELS") or BACKEND_DIR / "models")
# AI 를 돌릴 장치: auto = NVIDIA GPU 가 있으면 GPU, 없으면 CPU (cpu / cuda 로 고정할 수도 있다)
# 실행기(별도 프로세스)는 환경 변수를 물려받으므로, 여기서는 설명만 하고 실제 판단은 runner_utils.pick_device 가 한다
DEVICE = os.environ.get("VOCALCUT_DEVICE", "auto")
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

# 영상에 입히는 자막 글꼴. 글꼴 파일을 직접 지정해야 한글이 □□□ 로 나오지 않는다.
# - 윈도우: 맑은 고딕 (윈도우 기본 글꼴)
# - 리눅스 서버(Docker): 나눔고딕 (무료 공개 글꼴, apt 패키지 fonts-nanum)
# VOCALCUT_SUBTITLE_FONT / VOCALCUT_SUBTITLE_FONT_NAME 으로 바꿀 수 있다
if os.name == "nt":
    _font_file, _font_name = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "malgun.ttf", "Malgun Gothic"
else:
    _font_file, _font_name = Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), "NanumGothic"
SUBTITLE_FONT_FILE = Path(os.environ.get("VOCALCUT_SUBTITLE_FONT") or _font_file)
SUBTITLE_FONT_NAME = os.environ.get("VOCALCUT_SUBTITLE_FONT_NAME") or _font_name

# 미리 만들어 둔 화면(React 빌드 결과). 있으면 서버가 화면까지 한 주소에서 보여준다 (배포용).
# 개발할 때는 없어도 된다 (화면은 Vite 개발 서버 5173 이 보여줌)
FRONTEND_DIST = Path(os.environ.get("VOCALCUT_FRONTEND_DIST") or BACKEND_DIR.parent / "frontend" / "dist")

# 서버 기록 파일. VOCALCUT_LOG_FILE="" 이면 파일 기록을 끈다 (테스트용)
_log = os.environ.get("VOCALCUT_LOG_FILE")
LOG_FILE: Path | None = (BACKEND_DIR.parent / "logs" / "app.log") if _log is None else (Path(_log) if _log else None)

# 업로드 허용 확장자 (소문자, 점 포함)
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
ALLOWED_EXTS = ALLOWED_VIDEO_EXTS | ALLOWED_AUDIO_EXTS

# 업로드 최대 크기: 2GB
MAX_UPLOAD_BYTES = 2 * 1024**3
