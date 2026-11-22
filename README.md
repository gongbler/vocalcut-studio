# VocalCut Studio

로컬 PC에서 노래·영상을 편집하는 AI 스튜디오 (React + FastAPI + FFmpeg + Demucs + faster-whisper).

> ✅ Step 1 완료: 업로드 → 구간 자르기 · 볼륨 · 페이드 → MP4 / MP3 / WAV 다운로드
> ✅ Step 2 완료: 작업 대기열 · 파형 구간 선택 · **AI 보컬/MR 분리** · **믹서**(트랙별 볼륨·싱크·3밴드 EQ, 리미터)
> 🚧 Step 3 진행 중: ✅ AI 자동 자막(받아쓰기, 분리된 보컬 활용) · ✅ 자막 편집기(나누기·합치기·추가·되돌리기·저장) → 다음: SRT · 영상에 입히기

## 실행 방법

필수: Python 3.11, Node.js 20+, FFmpeg (PATH 등록)

```powershell
# 1) 백엔드 최초 설치 (한 번만)
powershell -ExecutionPolicy Bypass -File .\scripts\setup-backend.ps1

# 2) 백엔드 실행 → http://127.0.0.1:8000/docs
powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1

# 3) 프론트엔드 (새 터미널)
cd frontend
npm install
npm run dev   # → http://localhost:5173
```

### (선택) AI 보컬/MR 분리 설치

서버 자체에는 필요 없고, 분리 기능을 쓸 때만 별도 프로세스에서 사용한다. 설치하지 않으면 화면에 "AI 분리 없음"으로 표시된다.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

모델(`htdemucs`, 약 81MB)은 처음 분리할 때 `backend/models/`에 자동으로 받고, 이후에는 인터넷 없이 동작한다.

### (선택) AI 자동 자막 설치

PyTorch 없이 동작한다 (CTranslate2 엔진). 모델(small 약 460MB)은 처음 쓸 때 `backend/models/`에 받는다.

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-asr.txt
```

## 테스트

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 최초 1회
.\.venv\Scripts\python.exe -m pytest -v
```

- 테스트용 음원·영상은 FFmpeg로 즉석 생성하며, 볼륨·페이드·싱크·EQ·리미터는 `volumedetect`로 실제 음량을 측정해 검증한다.
  - 구간 측정은 `-ss/-t` 대신 `atrim` 필터를 쓴다 (`-ss/-t`는 약 0.09초 덩어리 단위라 짧은 구간 측정이 부정확했음).
- 보컬 분리는 같은 통신 규칙(JSON 줄)을 쓰는 **가짜 실행기**로 검사한다 → torch 없이도, 몇 초 안에 테스트가 끝난다.

## 설계 메모

### 보컬 분리: 저사양 PC(RAM 4GB, GPU 없음) 대응

| 방식 | 2분 곡 최대 메모리 | 비고 |
|---|---|---|
| Demucs 기본 (곡 전체를 한 번에) | 약 1.6GB (추정, 곡 길이에 비례) | 30초 753MB · 60초 1,048MB 실측 |
| **30초 조각 처리 + 2초 크로스페이드** | **813MB (실측, 곡 길이와 무관)** | 이음매 오차 = 이음매 없는 구간과 동일 |

- AI는 **별도 프로세스**에서 실행 → 서버는 torch를 불러오지 않으며, 분리가 끝나면 메모리를 전부 돌려받는다.
- 작업 대기열(작업자 1명)로 무거운 작업이 동시에 돌지 않게 하고, 취소 시 1~2초 안에 실행기 프로세스를 종료한다.
- 처리 속도: i5-4200M(CPU) 기준 곡 길이의 약 2.5~3.4배.

### 자동 자막: 모델 크기 실측 (i5-4200M, RAM 4GB, CPU int8)

| 모델 | 최대 메모리 | 받아쓰기 속도 (곡 길이 대비) | 한국어 글자 오류율 (음성 / 음성+반주) |
|---|---|---|---|
| tiny | 250MB | 0.15~0.4배 | 6.1% / 8.7% |
| base | 325MB | 0.25~0.35배 | 5.2% / 2.6% |
| small | 580~710MB | 0.45~0.8배 | **0.9% / 1.7%** |

- 측정 도구: `backend/tools/bench_transcription.py` (한국어는 정답을 아는 합성 음성으로 측정).
- 반주만 있는 구간에서 VAD(무음 건너뛰기)를 끄면 없는 가사("고맙습니다")를 지어냈다 → **VAD 기본 켜기**.
- 노래(영어 보컬 60초)에서 small 은 첫 줄을 빠뜨리는 경우가 있었다 → 사람이 고치는 편집기(3-3)를 전제로 한다.
- 실제 곡(3분 33초, 영어) 테스트에서 찾은 문제와 해결:

  | 문제 | 원인 | 해결 | 결과 |
  |---|---|---|---|
  | 자막이 0:39에서 끊김 | 영어 노래를 '한국어'로 받아 적게 함 | 기본값을 **자동 감지**로, 언어를 따로 감지해 다르면 경고 | 끝(3:26)까지 |
  | 원곡에서 노래를 많이 놓침 (10줄) | VAD 가 반주 위의 노래를 '목소리 아님'으로 버림 | 원곡은 VAD 기준 0.5 → 0.2 (보컬 트랙은 그대로) | 26줄, MR 만 넣으면 여전히 0줄 |
  | (참고) 분리된 보컬 사용 | 반주가 없어 AI 가 잘 들음 | 분리돼 있으면 보컬로 받아 적기가 기본 | base 41줄 · small 47줄 |

### 엔진 교체 구조 (상용화 대비)

`backend/app/services/engines/base.py`의 규격(`MediaEngine`, `SeparatorEngine`)만 지키면 엔진을 바꿔 끼울 수 있다.
설정(`app/core/config.py`)의 `MEDIA_ENGINE`, `SEPARATOR_ENGINE` 값으로 선택한다.

### ⚠️ 라이선스 메모

- Demucs **코드**는 MIT 라이선스.
- 사전학습 **모델 가중치**는 연구용 데이터셋으로 학습되었으므로, 유료 판매 전에 상업 이용이 가능한 모델로 교체를 검토해야 한다.
- faster-whisper 코드와 Whisper 모델 가중치는 MIT 라이선스 (상업 이용 가능).
- FFmpeg full build는 GPL 구성 요소를 포함한다 → 배포 시 LGPL 빌드 또는 대체 엔진 검토 필요.

## 구조

```
frontend/   React + Vite + TypeScript (화면)
backend/    FastAPI (API 서버, 작업 큐, 엔진 서비스 계층)
  app/services/engines/   엔진 규격(base) + FFmpeg 엔진 + Demucs·Whisper 실행기
  tools/                  성능 측정 도구 (bench_separation.py, bench_transcription.py)
scripts/    설치·실행 스크립트
```
