"""자막 내보내기 테스트: SRT/ASS 형식(순수 함수) + SRT 다운로드 + 영상에 입히기(한글이 진짜로 그려지는지)."""
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_job_manager, get_workspace
from app.core import config
from app.jobs.manager import JobManager
from app.main import app
from app.services.engines.media.ffmpeg_engine import FFmpegEngine, build_burn_command
from app.services.subtitle_formats import SubtitleStyle, to_ass, to_srt
from app.storage.workspace import Workspace
from tests.conftest import FFMPEG, requires_ffmpeg

LINES = [
    {"id": "b", "start": 62.5, "end": 65.004, "text": "두 번째 줄"},
    {"id": "a", "start": 0.5, "end": 1.25, "text": "첫 줄 {괄호} \\ 역슬래시"},
]


# ---------- 형식 (순수 함수) ----------

def test_srt_format_is_numbered_sorted_and_uses_comma_millis():
    srt = to_srt(LINES)
    assert srt.startswith("1\n00:00:00,500 --> 00:00:01,250\n첫 줄")       # 시간순으로 다시 번호
    assert "2\n00:01:02,500 --> 00:01:05,004\n두 번째 줄\n" in srt


def test_ass_matches_video_size_and_style():
    ass = to_ass(LINES, 1280, 720, SubtitleStyle(font_name="Malgun Gothic", size="large", position="top"))
    assert "PlayResX: 1280" in ass and "PlayResY: 720" in ass
    style = next(line for line in ass.splitlines() if line.startswith("Style: Default"))
    fields = style.split(",")
    assert fields[1] == "Malgun Gothic" and fields[2] == "58"               # 720 × 8% = 57.6 → 58px
    assert fields[18] == "8"                                                 # 8 = 위 가운데
    assert "Dialogue: 0,0:00:00.50,0:00:01.25,Default" in ass


def test_ass_escapes_special_characters():
    """{ } \\ 는 ASS 에서 '서식 명령'이라 그대로 두면 가사가 사라진다 → 보기엔 같은 전각 문자로."""
    dialogue = next(line for line in to_ass(LINES, 640, 360).splitlines() if "첫 줄" in line)
    text = dialogue.split(",,", 1)[1]
    assert "{" not in text and "}" not in text and "\\" not in text
    assert "｛괄호｝" in text and "＼" in text


# ---------- API ----------

@pytest.fixture
def client(tmp_path: Path):
    ws = Workspace(tmp_path / "workspace")
    ws.ensure()
    jobs = JobManager(ws.jobs)
    app.dependency_overrides[get_workspace] = lambda: ws
    app.dependency_overrides[get_job_manager] = lambda: jobs
    with TestClient(app) as c:
        c.ws = ws
        yield c
    app.dependency_overrides.clear()
    jobs.shutdown()


def wait_job(client, job_id, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.1)
    raise TimeoutError(job_id)


@pytest.fixture
def black_mp4(tmp_path: Path) -> Path:
    """검은 화면 2초 영상 (640x360) — 자막 글자만 밝게 보이므로 그려졌는지 세기 쉽다."""
    out = tmp_path / "black.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=640x360:d=2:r=25",
                    "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(out)], check=True)
    return out


def upload(client, path: Path, name: str) -> str:
    with open(path, "rb") as f:
        return client.post("/api/files", files={"file": (name, f)}).json()["id"]


def put_lines(client, file_id, lines):
    res = client.put(f"/api/files/{file_id}/subtitles", json={"segments": lines})
    assert res.status_code == 200, res.json()


def gray_frame(path: Path, at: float) -> bytes:
    return subprocess.run([FFMPEG, "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout


@requires_ffmpeg
def test_srt_download_has_bom_and_korean_filename(client, sine_wav):
    file_id = upload(client, sine_wav, "내 노래.wav")
    assert client.get(f"/api/files/{file_id}/subtitles.srt").status_code == 404   # 자막이 아직 없음
    put_lines(client, file_id, [{"start": 0.5, "end": 1.5, "text": "안녕하세요"}])

    res = client.get(f"/api/files/{file_id}/subtitles.srt")
    assert res.status_code == 200
    assert res.content.startswith(b"\xef\xbb\xbf")                           # UTF-8 BOM (메모장 한글 깨짐 방지)
    assert "안녕하세요" in res.content.decode("utf-8-sig")
    assert "filename*=UTF-8''%EB%82%B4%20%EB%85%B8%EB%9E%98.srt" in res.headers["content-disposition"]


@requires_ffmpeg
def test_burn_needs_video_and_subtitles(client, sine_wav, black_mp4):
    audio_id = upload(client, sine_wav, "노래.wav")
    put_lines(client, audio_id, [{"start": 0, "end": 1, "text": "가사"}])
    res = client.post("/api/subtitle-renders", json={"file_id": audio_id})
    assert res.status_code == 422 and "SRT" in res.json()["detail"]          # 소리만 있으면 SRT 로 안내

    video_id = upload(client, black_mp4, "영상.mp4")
    assert client.post("/api/subtitle-renders", json={"file_id": video_id}).status_code == 422  # 자막 없음


@requires_ffmpeg
def test_burned_video_shows_korean_text_only_while_line_is_on(client, black_mp4):
    video_id = upload(client, black_mp4, "내 영상.mp4")
    put_lines(client, video_id, [{"start": 0.0, "end": 1.0, "text": "가나다라마바사"}])

    job = wait_job(client, client.post("/api/subtitle-renders",
                                       json={"file_id": video_id, "size": "large"}).json()["id"])
    assert job["status"] == "done", job
    out = client.get(f"/api/outputs/{job['result']['output_id']}").json()
    assert out["download_name"] == "내 영상_자막.mp4"
    assert out["duration_sec"] == pytest.approx(2.0, abs=0.1)
    assert list(client.ws.temp.iterdir()) == []                              # 작업 폴더 정리

    path = client.ws.output_dir(out["id"]) / "result.mp4"
    bright = lambda frame: sum(1 for px in frame if px > 128)                # noqa: E731
    assert bright(gray_frame(path, 0.5)) > 500                               # 자막이 나오는 동안: 흰 글자
    assert bright(gray_frame(path, 1.5)) < 50                                # 끝난 뒤: 다시 검은 화면


@requires_ffmpeg
@pytest.mark.skipif(not config.SUBTITLE_FONT_FILE.is_file(), reason="한글 글꼴 파일이 없는 PC")
def test_korean_is_drawn_by_our_font_not_a_fallback(tmp_path, black_mp4):
    """한글이 □□□ 로 나오지 않는지: libass 기록에서
    - 우리가 지정한 글꼴(맑은 고딕)이 선택되고
    - 'Glyph ... not found'(이 글꼴에 그 글자가 없음 → 다른 글꼴을 찾아 헤맴)가 없어야 한다.
    """
    work = tmp_path / "burn"
    (work / "fonts").mkdir(parents=True)
    shutil.copy(config.SUBTITLE_FONT_FILE, work / "fonts")
    ass = work / "subs.ass"
    ass.write_text(to_ass([{"start": 0, "end": 2, "text": "한글 자막 테스트"}], 640, 360,
                          SubtitleStyle(font_name=config.SUBTITLE_FONT_NAME)), encoding="utf-8")
    engine = FFmpegEngine()
    cmd = build_burn_command(engine.ffmpeg, black_mp4, tmp_path / "out.mp4", ass, engine.probe(black_mp4),
                             work / "fonts")
    cmd[cmd.index("error")] = "verbose"                                      # 글꼴 선택 기록을 보기 위해
    log = subprocess.run(cmd, capture_output=True, cwd=work, check=True).stderr.decode("utf-8", "replace")

    assert "Loading font file 'fonts" in log                                 # 우리가 넣은 글꼴 파일을 읽었고
    assert "-> MalgunGothic" in log                                          # 그 글꼴이 선택됐고
    assert "not found" not in log                                            # 한글이 빠진 글자가 없다


def test_burn_command_keeps_windows_paths_out_of_the_filter(tmp_path):
    """필터(-vf)에는 'C:\\...' 같은 경로 대신 짧은 상대 이름만 들어가야 한다."""
    from app.services.engines.base import AudioStreamInfo, MediaInfo, VideoStreamInfo

    info = MediaInfo(path=Path("in.mp4"), format_name="mp4", duration_sec=2, size_bytes=1,
                     video=VideoStreamInfo("h264", 640, 360, 25), audio=AudioStreamInfo("aac", 44100, 2))
    folder = tmp_path / "내 폴더, [특수]"
    (folder / "fonts").mkdir(parents=True)
    cmd = build_burn_command("ffmpeg", Path("C:/a b/in.mp4"), Path("C:/a b/out.mp4"), folder / "subs.ass",
                             info, folder / "fonts")
    assert cmd[cmd.index("-vf") + 1] == "ass=subs.ass:fontsdir=fonts"
