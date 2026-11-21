import { postJson } from "./errors";
import type { Job } from "./jobs";

/** 보컬/MR 분리 주문 → 번호표. 완료되면 job.result = { vocals: 파일id, instrumental: 파일id } */
export function startSeparation(sourceId: string): Promise<Job> {
  return postJson<Job>("/api/separations", { source_id: sourceId });
}
