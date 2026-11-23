import { useState } from "react";
import { getMedia, type MediaFile } from "../../api/files";
import { cancelJob, JobCancelledError, waitForJob, type Job } from "../../api/jobs";
import { startSeparation } from "../../api/separations";
import JobProgress from "../../components/JobProgress";
import { useElapsed } from "../../hooks/useElapsed";
import { useHealth } from "../../hooks/useHealth";

export type Stems = { vocals: MediaFile; instrumental: MediaFile };

type Props = {
  source: MediaFile;
  stems: Stems | null;
  onSeparated: (stems: Stems) => void;
};

// 기록이 아직 없을 때 쓰는 기본값 (개발 PC i5-4200M 실측 중앙값)
const DEFAULT_RATIO = 2.95;

function estimate(durationSec: number, ratio: number | null): string {
  const minutes = Math.max(1, Math.round((durationSec * (ratio ?? DEFAULT_RATIO)) / 60));
  return `약 ${minutes}분`;
}

export default function SeparationPanel({ source, stems, onSeparated }: Props) {
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const elapsed = useElapsed(busy);

  // AI 분리 기능이 설치돼 있는지: 앱 전체가 공유하는 서버 상태에서 읽는다 (서버가 다시 켜지면 자동 갱신)
  const health = useHealth();
  const available =
    health.kind === "ok"
      ? { ok: health.data.separator.available, reason: health.data.separator.reason, ratio: health.data.separator.speed_ratio }
      : health.kind === "offline"
        ? { ok: false, reason: "서버에 연결할 수 없습니다.", ratio: null }
        : null;

  const start = async () => {
    setBusy(true);
    setJob(null);
    setCancelling(false);
    setError(null);
    try {
      const ticket = await startSeparation(source.id);
      setJob(ticket);
      const done = await waitForJob(ticket.id, setJob);
      // 결과는 '파일 id' 두 개 → 각각의 정보를 받아온다
      const [vocals, instrumental] = await Promise.all([
        getMedia(done.result!.vocals),
        getMedia(done.result!.instrumental),
      ]);
      onSeparated({ vocals, instrumental });
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
      <h2>🎤 보컬 / MR 분리 (AI)</h2>

      {stems ? (
        <p className="good">
          ✅ 분리 완료 — 위의 <b>보컬</b> · <b>MR</b> 탭에서 각 트랙을 듣고 편집·다운로드할 수 있어요.
        </p>
      ) : (
        <>
          <p className="hint">
            Demucs AI가 노래에서 목소리와 반주를 나눕니다.{" "}
            <b>{estimate(source.duration_sec, available?.ratio ?? null)}</b> 걸릴 것으로 예상돼요
            {available?.ratio ? " (이 PC의 최근 분리 기록 기준)" : " (첫 분리 전이라 기본값 기준)"}. 처리 중에도
            다른 편집은 대기열에서 순서를 기다립니다.
          </p>
          {available && !available.ok && <p className="bad">⚠️ 사용할 수 없음: {available.reason}</p>}
          {!busy && (
            <button onClick={start} disabled={!available?.ok}>
              보컬 / MR 분리 시작
            </button>
          )}
          {busy && (
            <>
              <JobProgress job={job} elapsed={elapsed} onCancel={cancel} cancelling={cancelling} />
              <p className="hint">💡 다른 브라우저 탭·프로그램을 닫아 두면 메모리 여유가 생겨 더 빨라져요.</p>
            </>
          )}
        </>
      )}
      {error && <p className="bad">❌ {error}</p>}
    </section>
  );
}
