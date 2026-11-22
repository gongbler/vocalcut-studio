// 자막 편집 동작(나누기·합치기·추가·검사)을 모아 둔 '순수 함수'들.
// 화면(React)과 분리해 두면: 입력 → 출력만 보면 되니 이해·검사가 쉽고, 다른 화면에서도 재사용할 수 있다.
// 모든 함수는 원래 배열을 고치지 않고 '새 배열'을 돌려준다 (React 가 바뀐 걸 알아채고, 되돌리기도 쉬움).
import type { SubtitleLine } from "../../api/subtitles";

export type Line = SubtitleLine;

const round2 = (n: number) => Math.round(n * 100) / 100;

/** 새 줄의 이름표 (서버와 같은 형식: 16진수 12자리) */
export const newId = () => crypto.randomUUID().replace(/-/g, "").slice(0, 12);

export const sortLines = (lines: Line[]) => [...lines].sort((a, b) => a.start - b.start || a.end - b.end);

/**
 * 한 줄을 둘로 나눈다.
 * - 글자: caret(커서 위치)에서 자른다. 커서가 맨 앞/맨 끝이면 가운데에서 가장 가까운 띄어쓰기에서 자른다.
 * - 시간: 재생 위치(atTime)가 그 줄 안에 있으면 거기서, 아니면 글자 수 비율로 나눈다.
 */
export function splitLine(lines: Line[], id: string, caret: number | null, atTime: number | null): Line[] {
  const i = lines.findIndex((l) => l.id === id);
  if (i < 0) return lines;
  const line = lines[i];
  const text = line.text;

  let cut = caret ?? 0;
  if (cut <= 0 || cut >= text.length) {
    const mid = text.length / 2;
    const spaces = [...text.matchAll(/\s/g)].map((m) => m.index!);
    cut = spaces.length ? spaces.reduce((a, b) => (Math.abs(b - mid) < Math.abs(a - mid) ? b : a)) : Math.floor(mid);
  }
  const left = text.slice(0, cut).trim();
  const right = text.slice(cut).trim();
  if (!left || !right) return lines; // 나눌 글자가 없음

  const inside = atTime !== null && atTime > line.start + 0.1 && atTime < line.end - 0.1;
  const t = round2(inside ? atTime : line.start + ((line.end - line.start) * left.length) / (left.length + right.length));

  const out = [...lines];
  out.splice(i, 1, { ...line, end: t, text: left }, { id: newId(), start: t, end: line.end, text: right });
  return out;
}

/** 이 줄과 바로 다음 줄을 하나로 합친다 (시간은 이 줄 시작 ~ 다음 줄 끝) */
export function mergeWithNext(lines: Line[], id: string): Line[] {
  const sorted = sortLines(lines);
  const i = sorted.findIndex((l) => l.id === id);
  if (i < 0 || i === sorted.length - 1) return lines;
  const a = sorted[i];
  const b = sorted[i + 1];
  const merged = { ...a, end: Math.max(a.end, b.end), text: `${a.text} ${b.text}`.trim() };
  return [...sorted.slice(0, i), merged, ...sorted.slice(i + 2)];
}

/** 재생 위치(at)에 빈 줄을 끼워 넣는다. 다음 줄과 겹치지 않게 길이를 줄인다 (기본 2초) */
export function insertLine(lines: Line[], at: number, duration: number): { lines: Line[]; id: string } {
  const start = round2(Math.max(0, Math.min(at, duration - 0.2)));
  const next = sortLines(lines).find((l) => l.start > start + 0.3);
  const end = round2(Math.min(start + 2, next ? next.start : Infinity, duration));
  const line = { id: newId(), start, end: Math.max(end, round2(start + 0.2)), text: "" };
  return { lines: sortLines([...lines, line]), id: line.id };
}

export type Problem = "empty" | "time" | "overlap" | "beyond";

/** 저장하기 전에 화면에서 미리 알려줄 문제들 (줄 id → 문제 목록). 서버도 같은 규칙으로 다시 검사한다. */
export function findProblems(lines: Line[], duration: number): Map<string, Problem[]> {
  const out = new Map<string, Problem[]>();
  const add = (id: string, p: Problem) => out.set(id, [...(out.get(id) ?? []), p]);
  const sorted = sortLines(lines);
  sorted.forEach((l, i) => {
    if (!l.text.trim()) add(l.id, "empty");
    if (!(l.end > l.start) || l.start < 0) add(l.id, "time");
    if (l.end > duration + 0.5) add(l.id, "beyond");
    const next = sorted[i + 1];
    if (next && next.start < l.end - 0.01) add(l.id, "overlap"); // 겹침은 저장은 되지만 화면에 두 줄이 동시에 뜬다
  });
  return out;
}

export const PROBLEM_TEXT: Record<Problem, string> = {
  empty: "글자가 비어 있어요",
  time: "끝 시간이 시작보다 뒤여야 해요",
  overlap: "다음 줄과 시간이 겹쳐요",
  beyond: "곡 길이를 넘어요",
};

/** 저장을 막는 문제 (겹침은 경고만) */
export const isBlocking = (p: Problem) => p !== "overlap";
