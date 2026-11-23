"""자막 파일 형식 만들기 (순수 함수: 줄 목록 → 글자).

- SRT: 거의 모든 플레이어·유튜브가 읽는 가장 단순한 자막 형식. "따로 저장"용.
- ASS: 글꼴·크기·위치·테두리까지 정할 수 있는 형식. FFmpeg(libass)로 "영상에 입히기"용.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Position = Literal["bottom", "middle", "top"]
Size = Literal["small", "medium", "large"]

# 글자 크기 = 영상 높이의 몇 % (720p 기준 small 32px · medium 43px · large 58px)
SIZE_RATIO: dict[str, float] = {"small": 0.045, "medium": 0.06, "large": 0.08}
# ASS 정렬 번호 = 숫자 키패드 배치 (2 = 아래 가운데, 5 = 가운데, 8 = 위 가운데)
ALIGNMENT: dict[str, int] = {"bottom": 2, "middle": 5, "top": 8}


@dataclass(frozen=True)
class SubtitleStyle:
    font_name: str = "Malgun Gothic"
    size: Size = "medium"
    position: Position = "bottom"


def _srt_time(sec: float) -> str:
    """12.345 → "00:00:12,345" (SRT 는 쉼표로 밀리초를 구분한다)"""
    ms = max(0, round(sec * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(lines: list[dict]) -> str:
    """SRT 형식:
        1
        00:00:01,500 --> 00:00:03,000
        첫 줄 가사
        (빈 줄)
    """
    blocks = []
    for n, line in enumerate(sorted(lines, key=lambda x: x["start"]), start=1):
        text = str(line["text"]).replace("\r", "").strip()
        blocks.append(f"{n}\n{_srt_time(line['start'])} --> {_srt_time(line['end'])}\n{text}\n")
    return "\n".join(blocks)


def _ass_time(sec: float) -> str:
    """12.345 → "0:00:12.35" (ASS 는 1/100초 단위)"""
    cs = max(0, round(sec * 100))
    h, rest = divmod(cs, 360_000)
    m, rest = divmod(rest, 6000)
    s, cs = divmod(rest, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    """ASS 에서 특별한 뜻이 있는 글자를 '그냥 글자'로 바꾼다.

    { } 는 '서식 명령' 시작/끝, \\ 는 명령 기호라서 그대로 두면 가사가 사라지거나 이상하게 보인다.
    """
    text = text.replace("\\", "＼")  # 전각 역슬래시: 보기엔 같고 명령으로 읽히지 않음
    text = text.replace("{", "｛").replace("}", "｝")
    return text.replace("\r", "").replace("\n", r"\N")  # \N = ASS 의 줄바꿈


def to_ass(lines: list[dict], width: int, height: int, style: SubtitleStyle = SubtitleStyle()) -> str:
    """영상 크기(width×height)에 맞춘 ASS 자막.

    PlayResX/Y 를 영상 크기와 같게 두면, 글자 크기·여백을 '영상 픽셀' 단위로 정할 수 있다.
    """
    font_px = max(12, round(height * SIZE_RATIO[style.size]))
    outline = max(1, round(font_px * 0.08))   # 검은 테두리: 밝은 화면에서도 글자가 보이게
    margin_v = round(height * 0.06)           # 화면 가장자리에서 띄우는 거리
    margin_h = round(width * 0.05)

    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",                       # 긴 줄은 자동으로 줄바꿈 (줄 길이를 고르게)
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # 색은 &HAABBGGRR (AA=투명도). 흰 글자 · 검은 테두리 · 반투명 그림자
        f"Style: Default,{style.font_name},{font_px},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},1,{ALIGNMENT[style.position]},{margin_h},{margin_h},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = [
        f"Dialogue: 0,{_ass_time(l['start'])},{_ass_time(l['end'])},Default,,0,0,0,,{_ass_text(str(l['text']))}"
        for l in sorted(lines, key=lambda x: x["start"])
    ]
    return header + "\n" + "\n".join(events) + "\n"
