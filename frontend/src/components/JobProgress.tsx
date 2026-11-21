import type { Job } from "../api/jobs";

/** 작업 진행 상태 표시줄 (편집·보컬 분리·믹싱에서 공통으로 사용) */
export default function JobProgress({ job, elapsed }: { job: Job | null; elapsed: number }) {
  const percent = Math.round((job?.progress ?? 0) * 100);
  const label =
    !job || job.status === "queued"
      ? "대기 중… (앞 작업이 끝나면 시작)"
      : `${job.message ?? "처리 중"} ${percent}%`;

  return (
    <div className="job-progress" role="status" aria-live="polite">
      <div className="row space-between">
        <span>⏳ {label}</span>
        <span className="hint">{elapsed}초 경과</span>
      </div>
      <div className="progress">
        <div className="bar" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
