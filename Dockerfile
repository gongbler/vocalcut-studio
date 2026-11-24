# VocalCut Studio 데모 서버 이미지 = '이사용 컨테이너 한 상자'.
#
# 화면(React) + 서버(FastAPI) + FFmpeg + AI 패키지 + AI 모델 + 한글 글꼴을 한 상자에 담는다.
# 어디서 열어도(Hugging Face Spaces, 클라우드 GPU 서버…) 똑같이 동작한다.
#
#   빌드:  docker build -t vocalcut .
#   실행:  docker run -p 7860:7860 vocalcut      → http://localhost:7860
#
# GPU 서버(C안)로 옮길 때: --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 처럼
# CUDA 용 PyTorch 주소만 바꾸면 된다. 장치는 VOCALCUT_DEVICE=auto 가 알아서 GPU 를 고른다.

# ---------- 1단계: 화면 만들기 (Node) ----------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 2단계: 서버 상자 (Python) ----------
FROM python:3.11-slim

# FFmpeg: 미디어 처리 / fonts-nanum: 자막용 한글 글꼴(나눔고딕, 무료 공개 글꼴)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces 는 UID 1000 사용자로 실행한다 → 같은 사용자를 만들어 둔다
RUN useradd -m -u 1000 user

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# 패키지 설치 (코드보다 먼저 → 코드만 바뀌면 이 무거운 단계는 캐시를 다시 쓴다)
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
COPY backend/requirements.txt backend/requirements-ai.txt backend/requirements-asr.txt ./
RUN pip install torch==2.15.0 torchaudio==2.11.1 --index-url ${TORCH_INDEX} \
    && pip install -r requirements.txt -r requirements-ai.txt -r requirements-asr.txt

# AI 모델을 상자 안에 미리 받아 둔다 → 첫 사용자가 다운로드를 기다리지 않는다
ENV VOCALCUT_MODELS=/app/models
COPY backend/app ./app
COPY backend/tools/prefetch_models.py ./tools/prefetch_models.py
RUN python tools/prefetch_models.py && chown -R user:user /app/models

# 미리 만든 화면 파일
COPY --from=web /web/dist /app/frontend/dist

# 데모 사이트 설정 (값은 docker run -e 로 바꿀 수 있다)
ENV VOCALCUT_DEMO=1 \
    VOCALCUT_FRONTEND_DIST=/app/frontend/dist \
    VOCALCUT_WORKSPACE=/tmp/vocalcut/workspace \
    VOCALCUT_LOG_FILE=/tmp/vocalcut/logs/app.log \
    VOCALCUT_COOKIE_CROSS_SITE=1 \
    VOCALCUT_DEVICE=auto

USER user
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
