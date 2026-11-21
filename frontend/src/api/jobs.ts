// 작업 대기열(번호표) 조회 함수
import { errorMessage } from "./errors";

export type JobStatus = "queued" | "running" | "done" | "error";

export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number; // 0 ~ 1
  message: string | null;
  error: string | null;
  result: Record<string, string> | null;
};

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as Job;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 작업이 끝날 때까지 1초마다 상태를 물어본다 (폴링).
 * 상태가 바뀔 때마다 onUpdate 로 알려주고, 완료되면 Job 을, 실패하면 에러를 던진다.
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
    if (job.status === "error") throw new Error(job.error ?? "작업이 실패했습니다.");
    await sleep(intervalMs);
  }
}
