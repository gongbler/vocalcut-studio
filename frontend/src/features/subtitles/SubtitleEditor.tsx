import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { saveSubtitles, type Subtitles } from "../../api/subtitles";
import { formatDuration } from "../../utils/format";
import {
  findProblems,
  insertLine,
  isBlocking,
  mergeWithNext,
  PROBLEM_TEXT,
  sortLines,
  splitLine,
  type Line,
} from "./editing";

type Props = {
  fileId: string;
  duration: number;
  initial: Subtitles;
  playerRef: RefObject<HTMLMediaElement | null>;
  onSaved: (subs: Subtitles) => void;
  onDirtyChange: (dirty: boolean) => void;
};

const HISTORY_LIMIT = 100;

/** 자막 편집기: 글자·시간 고치기, 나누기/합치기/추가/삭제, 되돌리기, 저장 */
export default function SubtitleEditor({ fileId, duration, initial, playerRef, onSaved, onDirtyChange }: Props) {
  const [lines, setLines] = useState<Line[]>(initial.segments);
  const [saved, setSaved] = useState<Line[]>(initial.segments); // 마지막으로 저장된 상태 (비교용)
  const [now, setNow] = useState(0);
  const [follow, setFollow] = useState(true); // 재생 위치를 따라 목록 스크롤
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 되돌리기: 바꾸기 '직전' 상태를 쌓아 둔다.
  // 글자를 한 자 칠 때마다 쌓으면 되돌리기를 수십 번 눌러야 하므로, 같은 칸을 연달아 고치면 한 번으로 묶는다(key).
  const history = useRef<Line[][]>([]);
  const lastKey = useRef<string | null>(null);
  const carets = useRef(new Map<string, number>()); // 줄마다 마지막 커서 위치 (나누기용)
  const rowRefs = useRef(new Map<string, HTMLLIElement>());

  const dirty = lines !== saved && JSON.stringify(lines) !== JSON.stringify(saved);
  const problems = useMemo(() => findProblems(lines, duration), [lines, duration]);
  const blocking = [...problems.values()].some((ps) => ps.some(isBlocking));
  const playingId = lines.find((l) => now >= l.start && now < l.end)?.id;

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  // 저장 안 한 채로 창을 닫으려 하면 브라우저가 한 번 물어보게 한다
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    const timer = setInterval(() => setNow(playerRef.current?.currentTime ?? 0), 250);
    return () => clearInterval(timer);
  }, [playerRef]);

  // 지금 나오는 줄이 바뀌면 목록에서 보이게 스크롤 (글자를 고치는 중에는 화면이 튀지 않게 멈춤)
  useEffect(() => {
    if (!follow || !playingId || playerRef.current?.paused) return;
    if (document.activeElement?.closest(".sub-row")) return;
    rowRefs.current.get(playingId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [playingId, follow, playerRef]);

  // 최신 줄 목록을 ref 에도 들고 있는다 → 버튼을 빠르게 연달아 눌러도 '옛날 값'으로 계산하지 않는다 (2-5 싱크 버그와 같은 원리)
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const [canUndo, setCanUndo] = useState(false);

  /** 모든 변경은 여기를 거친다 → 되돌리기 기록이 한 곳에서 관리된다 */
  const commit = (next: Line[] | ((cur: Line[]) => Line[]), key: string | null = null) => {
    const cur = linesRef.current;
    const value = typeof next === "function" ? next(cur) : next;
    if (value === cur) return;
    if (key === null || key !== lastKey.current) {
      history.current = [...history.current.slice(-HISTORY_LIMIT + 1), cur];
    }
    lastKey.current = key;
    linesRef.current = value;
    setLines(value);
    setCanUndo(true);
    setNotice(null);
  };

  const undo = () => {
    const prev = history.current.pop();
    if (!prev) return;
    lastKey.current = null;
    linesRef.current = prev;
    setLines(prev);
    setCanUndo(history.current.length > 0);
  };

  // Ctrl+Z: 글자 칸 안에서는 브라우저 자체 되돌리기(글자 단위)를 쓰고, 밖에서는 편집기 되돌리기
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea");
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey && !typing) {
        e.preventDefault();
        undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const patch = (id: string, field: "start" | "end" | "text", value: string | number) =>
    commit((cur) => cur.map((l) => (l.id === id ? { ...l, [field]: value } : l)), `${field}:${id}`);

  const playerTime = () => playerRef.current?.currentTime ?? 0;

  const seek = (sec: number) => {
    const p = playerRef.current;
    if (!p) return;
    p.currentTime = sec;
    void p.play().catch(() => undefined);
  };

  const add = () => {
    const { lines: next, id } = insertLine(linesRef.current, playerTime(), duration);
    commit(next);
    // 새 줄의 글자 칸에 바로 커서를 둔다
    requestAnimationFrame(() => rowRefs.current.get(id)?.querySelector("textarea")?.focus());
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const result = await saveSubtitles(fileId, sortLines(lines));
      setLines(result.segments);
      setSaved(result.segments);
      history.current = [];
      lastKey.current = null;
      setCanUndo(false);
      setNotice("✅ 저장했어요.");
      onSaved(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    if (!confirm("저장하지 않은 변경을 모두 버리고 마지막 저장 상태로 돌아갈까요?")) return;
    commit(saved);
  };

  return (
    <div className="sub-editor">
      <div className="row space-between sub-toolbar">
        <span className="row">
          <button className="small" onClick={add} title="플레이어의 현재 위치에 새 줄을 넣어요 (AI가 빠뜨린 가사 추가)">
            ＋ 현재 위치에 줄 추가
          </button>
          <button className="small" onClick={undo} disabled={!canUndo} title="Ctrl+Z">
            ↶ 되돌리기
          </button>
          <label className="row hint">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
            재생 위치 따라가기
          </label>
        </span>
        <span className="row">
          {dirty && (
            <button className="small" onClick={discard}>
              변경 버리기
            </button>
          )}
          <button onClick={save} disabled={!dirty || saving || blocking}>
            {saving ? "저장 중…" : dirty ? "💾 저장" : "저장됨"}
          </button>
        </span>
      </div>
      {blocking && <p className="bad">⚠️ 빨간 표시가 있는 줄을 고쳐야 저장할 수 있어요.</p>}
      {error && <p className="bad">❌ {error}</p>}
      {notice && !dirty && <p className="good">{notice}</p>}

      <ol className="sub-rows">
        {lines.map((l, i) => {
          const ps = problems.get(l.id) ?? [];
          const bad = ps.some(isBlocking);
          return (
            <li
              key={l.id}
              ref={(el) => {
                if (el) rowRefs.current.set(l.id, el);
                else rowRefs.current.delete(l.id);
              }}
              className={`sub-row ${l.id === playingId ? "playing" : ""} ${bad ? "invalid" : ""}`}
            >
              <div className="row sub-times">
                <button className="small" onClick={() => seek(l.start)} title="이 줄부터 재생">
                  ▶ {i + 1}
                </button>
                <label className="row">
                  시작
                  <input type="number" step={0.1} min={0} value={l.start}
                    onChange={(e) => patch(l.id, "start", Number(e.target.value))} aria-label={`${i + 1}번 줄 시작(초)`} />
                </label>
                <button className="small" onClick={() => patch(l.id, "start", Math.round(playerTime() * 100) / 100)}
                  title="플레이어의 현재 위치를 시작 시간으로">⏱</button>
                <label className="row">
                  끝
                  <input type="number" step={0.1} min={0} value={l.end}
                    onChange={(e) => patch(l.id, "end", Number(e.target.value))} aria-label={`${i + 1}번 줄 끝(초)`} />
                </label>
                <button className="small" onClick={() => patch(l.id, "end", Math.round(playerTime() * 100) / 100)}
                  title="플레이어의 현재 위치를 끝 시간으로">⏱</button>
                <span className="hint">
                  {formatDuration(l.start)} → {formatDuration(l.end)}
                </span>
              </div>
              <textarea
                rows={1}
                value={l.text}
                placeholder="가사를 입력하세요"
                onChange={(e) => patch(l.id, "text", e.target.value)}
                onSelect={(e) => carets.current.set(l.id, e.currentTarget.selectionStart)}
                aria-label={`${i + 1}번 줄 글자`}
              />
              <div className="row space-between">
                <span className="bad hint-bad">{ps.map((p) => PROBLEM_TEXT[p]).join(" · ")}</span>
                <span className="row">
                  <button className="small" title="커서 위치에서 글자를, 재생 위치(또는 글자 비율)에서 시간을 나눠요"
                    onClick={() => commit(splitLine(linesRef.current, l.id, carets.current.get(l.id) ?? null, playerTime()))}>
                    ✂ 나누기
                  </button>
                  <button className="small" disabled={i === lines.length - 1}
                    onClick={() => commit((cur) => mergeWithNext(cur, l.id))}>
                    ⤓ 다음 줄과 합치기
                  </button>
                  <button className="small" aria-label={`${i + 1}번 줄 삭제`}
                    onClick={() => commit((cur) => cur.filter((x) => x.id !== l.id))}>
                    🗑 삭제
                  </button>
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      {lines.length === 0 && <p className="hint">줄이 없어요. 재생하다가 "＋ 현재 위치에 줄 추가"로 직접 만들 수 있어요.</p>}
    </div>
  );
}
