// 작업 대기열(번호표) 조회 / 취소 함수
import { errorMessage, postJson } from "./errors";

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number; // 0 ~ 1
  message: string | null;
  error: string | null;
  result: Record<string, string> | null;
};

/** 사용자가 취소한 작업 — 일반 에러와 구분해서 '실패' 메시지를 띄우지 않기 위함 */
export class JobCancelledError extends Error {
  constructor() {
    super("작업이 취소되었습니다.");
    this.name = "JobCancelledError";
  }
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as Job;
}

export function cancelJob(id: string): Promise<Job> {
  return postJson<Job>(`/api/jobs/${id}/cancel`, {});
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 작업이 끝날 때까지 1초마다 상태를 물어본다 (폴링).
 * 상태가 바뀔 때마다 onUpdate 로 알려주고, 완료되면 Job 을, 실패/취소되면 에러를 던진다.
 */
export async function waitForJob(
  id: string,
  onUpdate: (job: Job) => void,
  intervalMs = 1000,
): Promise<Job> {
  let networkFailures = 0;
  for (;;) {
    let job: Job;
    try {
      job = await getJob(id);
      networkFailures = 0;
    } catch (err) {
      // 서버가 잠깐 재시작되는 중일 수 있으니 몇 번은 참고 다시 묻는다
      if (++networkFailures >= 5) throw err;
      await sleep(intervalMs);
      continue;
    }
    onUpdate(job);
    if (job.status === "done") return job;
    if (job.status === "cancelled") throw new JobCancelledError();
    if (job.status === "error") throw new Error(job.error ?? "작업이 실패했습니다.");
    await sleep(intervalMs);
  }
}
