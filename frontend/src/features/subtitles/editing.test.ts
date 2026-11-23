// 자막 편집 동작(순수 함수) 테스트 — 화면 없이 '입력 → 출력'만 확인한다.  실행: npm.cmd test
import { describe, expect, it } from "vitest";
import { findProblems, insertLine, mergeWithNext, splitLine, type Line } from "./editing";

const line = (id: string, start: number, end: number, text: string): Line => ({ id, start, end, text });

describe("splitLine (나누기)", () => {
  const lines = [line("a", 10, 14, "오늘 밤 창문을 열면 바람이 불어와")];

  it("커서 위치에서 글자를, 재생 위치에서 시간을 나눈다", () => {
    const caret = lines[0].text.indexOf("바람"); // 커서를 "바람" 바로 앞에 둔 상태
    const out = splitLine(lines, "a", caret, 12.5);
    expect(out.map((l) => l.text)).toEqual(["오늘 밤 창문을 열면", "바람이 불어와"]);
    expect([out[0].start, out[0].end, out[1].start, out[1].end]).toEqual([10, 12.5, 12.5, 14]);
    expect(out[0].id).toBe("a"); // 앞쪽은 원래 이름표 유지
    expect(out[1].id).toMatch(/^[0-9a-f]{12}$/); // 뒤쪽은 새 이름표 (서버 형식과 같음)
  });

  it("재생 위치가 줄 밖이면 글자 수 비율로 시간을 나눈다", () => {
    const out = splitLine(lines, "a", 10, 99);
    expect(out[0].end).toBeGreaterThan(10);
    expect(out[0].end).toBeLessThan(14);
    expect(out[0].end).toBe(out[1].start); // 빈틈·겹침 없음
  });

  it("커서가 맨 앞/끝이면 가운데에 가까운 띄어쓰기에서 자른다", () => {
    const out = splitLine([line("a", 0, 4, "하나 둘 셋 넷")], "a", 0, null);
    expect(out.map((l) => l.text)).toEqual(["하나 둘", "셋 넷"]);
  });

  it("나눌 글자가 없으면 그대로 둔다", () => {
    const one = [line("a", 0, 1, "음")];
    expect(splitLine(one, "a", 1, null)).toBe(one);
  });
});

describe("mergeWithNext (합치기)", () => {
  it("다음 줄과 글자·시간을 합친다 (순서가 섞여 있어도 시간순 기준)", () => {
    const out = mergeWithNext([line("b", 3, 5, "둘째"), line("a", 1, 2, "첫째")], "a");
    expect(out).toEqual([line("a", 1, 5, "첫째 둘째")]);
  });

  it("마지막 줄은 합칠 대상이 없다", () => {
    const lines = [line("a", 1, 2, "끝")];
    expect(mergeWithNext(lines, "a")).toBe(lines);
  });
});

describe("insertLine (줄 추가)", () => {
  it("빈 곳에 2초짜리 줄을 넣고, 다음 줄과 겹치지 않게 줄인다", () => {
    const { lines, id } = insertLine([line("a", 0, 2, "앞"), line("b", 6, 8, "뒤")], 5, 60);
    const added = lines.find((l) => l.id === id)!;
    expect([added.start, added.end, added.text]).toEqual([5, 6, ""]);
    expect(lines.map((l) => l.id)).toEqual(["a", id, "b"]); // 시간순 자리에 들어감
  });

  it("이미 있는 줄의 중간에 넣으면, 그 줄을 거기서 끝내서 겹치지 않게 한다", () => {
    const { lines, id } = insertLine([line("a", 10, 20, "긴 줄")], 15, 60);
    expect(lines.find((l) => l.id === "a")!.end).toBe(15);
    expect(findProblems(lines, 60).size).toBe(1); // 새 줄은 비어 있음(empty) 문제만, 겹침(overlap) 없음
    expect(findProblems(lines, 60).get(id)).toEqual(["empty"]);
  });

  it("곡 끝을 넘지 않는다", () => {
    const { lines } = insertLine([], 59.5, 60);
    expect(lines[0].end).toBeLessThanOrEqual(60);
  });
});

describe("findProblems (저장 전 검사)", () => {
  it("빈 글자·거꾸로 된 시간·곡 길이 초과·겹침을 찾아낸다", () => {
    const p = findProblems(
      [line("e", 0, 1, " "), line("t", 3, 2, "거꾸로"), line("o1", 4, 6, "겹침"), line("o2", 5, 7, "x"), line("x", 9, 99, "넘침")],
      10,
    );
    expect(p.get("e")).toEqual(["empty"]);
    expect(p.get("t")).toContain("time");
    expect(p.get("o1")).toEqual(["overlap"]);
    expect(p.get("x")).toEqual(["beyond"]);
  });
});
