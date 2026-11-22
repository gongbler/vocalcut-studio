import { useEffect, useState, type RefObject } from "react";
import { getHealth } from "../../api/client";
import type { MediaFile } from "../../api/files";
import { cancelJob, JobCancelledError, waitForJob, type Job } from "../../api/jobs";
import { getSubtitles, startTranscription, type Subtitles } from "../../api/subtitles";
import JobProgress from "../../components/JobProgress";
import { useElapsed } from "../../hooks/useElapsed";
import type { Stems } from "../separation/SeparationPanel";
import SubtitleEditor from "./SubtitleEditor";

type Props = {
  source: MediaFile;
  stems: Stems | null;
  playerRef: RefObject<HTMLMediaElement | null>;
};

type Model = { id: string; label: string };

// '자동 감지'가 기본: 실측에서 영어 노래를 '한국어'로 받아 적게 하자 39초에서 멈췄다
const LANGUAGES = [
  { id: "auto", label: "자동 감지 (권장)" },
  { id: "ko", label: "한국어" },
  { id: "en", label: "영어" },
  { id: "ja", label: "일본어" },
];

const languageName = (code: string | null) =>
  ({ ko: "한국어", en: "영어", ja: "일본어", zh: "중국어" })[code ?? ""] ?? code ?? "알 수 없음";

// 이 PC(i5-4200M) 실측: 받아쓰기 시간 ÷ 곡 길이 (+ 모델 불러오기 몇 초)
const SPEED: Record<string, { ratio: number; load: number }> = {
  small: { ratio: 0.8, load: 7 },
  base: { ratio: 0.35, load: 4 },
};

function estimate(durationSec: number, model: string): string {
  const s = SPEED[model] ?? SPEED.small;
  const sec = durationSec * s.ratio + s.load;
  return sec < 60 ? `약 ${Math.max(10, Math.round(sec / 10) * 10)}초` : `약 ${Math.round(sec / 60)}분`;
}

export default function SubtitlePanel({ source, stems, playerRef }: Props) {
  const [health, setHealth] = useState<{ ok: boolean; reason: string | null; models: Model[] } | null>(null);
  const [model, setModel] = useState("small");
  const [language, setLanguage] = useState("auto");
  const [useVocals, setUseVocals] = useState(true);
  const [subs, setSubs] = useState<Subtitles | null>(null);

  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0); // 받아쓰기를 새로 할 때마다 +1
  const [dirty, setDirty] = useState(false); // 편집기에 저장 안 한 변경이 있는지
  const elapsed = useElapsed(busy);

  useEffect(() => {
    getHealth()
      .then((h) => {
        setHealth({ ok: h.transcriber.available, reason: h.transcriber.reason, models: h.transcriber.models });
        setModel(h.transcriber.default_model);
      })
      .catch(() => setHealth({ ok: false, reason: "서버에 연결할 수 없습니다.", models: [] }));
    // 예전에 받아 둔 자막이 있으면 불러온다 (새로고침해도 다시 받아 적지 않게)
    getSubtitles(source.id).then(setSubs).catch(() => undefined);
  }, [source.id]);

  const start = async () => {
    if (dirty && !confirm("저장하지 않은 자막 수정이 있어요. 다시 받아 적으면 사라져요. 계속할까요?")) return;
    if (subs?.edited && !dirty && !confirm("직접 고친 자막을 AI 결과로 덮어써요. 계속할까요?")) return;
    setBusy(true);
    setJob(null);
    setCancelling(false);
    setError(null);
    try {
      const ticket = await startTranscription({ file_id: source.id, model, language, use_vocals: useVocals });
      setJob(ticket);
      await waitForJob(ticket.id, setJob);
      setSubs(await getSubtitles(source.id));
      setGeneration((g) => g + 1);
    } catch (err) {
      if (!(err instanceof JobCancelledError)) setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!job) return;
    setCancelling(true);
    await cancelJob(job.id).catch(() => undefined);
  };

  return (
    <section className="card">
      <h2>💬 자동 자막 (AI)</h2>
      <p className="hint">
        Whisper AI가 가사·대사를 받아 적어요. <b>{estimate(source.duration_sec, model)}</b> 걸릴 것으로 예상돼요.
        AI가 만든 <b>초안</b>이라 틀린 곳은 다음 단계의 편집기에서 고칠 수 있어요.
      </p>
      {health && !health.ok && <p className="bad">⚠️ 사용할 수 없음: {health.reason}</p>}

      <div className="field-grid">
        <fieldset className="formats">
          <legend>모델</legend>
          <div className="row">
            {(health?.models ?? []).map((m) => (
              <label key={m.id} className={`chip ${model === m.id ? "on" : ""}`}>
                <input type="radio" name="asr-model" checked={model === m.id} onChange={() => setModel(m.id)} />
                {m.id} · {m.label}
              </label>
            ))}
          </div>
        </fieldset>
        <label>
          언어
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <div className="span-2">
          {stems ? (
            <label className="row">
              <input type="checkbox" checked={useVocals} onChange={(e) => setUseVocals(e.target.checked)} />
              분리된 <b>보컬 트랙</b>으로 받아 적기 (반주가 없어 더 정확해요)
            </label>
          ) : (
            <p className="hint">💡 노래라면 위에서 먼저 보컬/MR 분리를 하면 반주 없이 받아 적어 더 정확해요.</p>
          )}
        </div>
      </div>

      {!busy && (
        <button onClick={start} disabled={!health?.ok}>
          {subs ? "🔁 다시 받아 적기 (지금 자막을 덮어써요)" : "💬 자막 만들기"}
        </button>
      )}
      {busy && <JobProgress job={job} elapsed={elapsed} onCancel={cancel} cancelling={cancelling} />}
      {error && <p className="bad">❌ {error}</p>}

      {subs && (
        <>
          <p className="hint" style={{ marginTop: 14 }}>
            {subs.segments.length}줄 · 모델 {subs.model} · {languageName(subs.language)} ·{" "}
            {subs.audio_source === "vocals" ? "보컬 트랙" : "원본 소리"}로 받아 적음 {subs.edited ? " · ✏️ 고친 자막" : ""} — ▶ 를 누르면 그 줄부터 재생돼요.
          </p>
          {subs.language_mismatch && (
            <p className="bad">
              ⚠️ 이 소리는 <b>{languageName(subs.language_mismatch.detected)}</b>로 들려요 (선택한 언어:{" "}
              {languageName(subs.language_mismatch.chosen)}). 언어가 다르면 AI가 중간에 받아쓰기를 멈출 수 있어요 →
              언어를 <b>자동 감지</b>나 <b>{languageName(subs.language_mismatch.detected)}</b>로 바꿔 다시 받아 적으세요.
            </p>
          )}
          {subs.segments.length === 0 && <p className="bad">⚠️ 받아 적은 말이 없어요. 언어 설정을 확인해 보세요.</p>}
          <SubtitleEditor
            key={generation} // 새로 받아 적으면 편집기를 새 결과로 다시 시작
            fileId={source.id}
            duration={source.duration_sec}
            initial={subs}
            playerRef={playerRef}
            onSaved={setSubs}
            onDirtyChange={setDirty}
          />
        </>
      )}
    </section>
  );
}
