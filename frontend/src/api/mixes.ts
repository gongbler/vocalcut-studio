import { postJson } from "./errors";
import type { Job } from "./jobs";

export type MixTrackIn = {
  file_id: string;
  volume_db: number;
  offset_sec: number;
  eq_low_db: number;
  eq_mid_db: number;
  eq_high_db: number;
  muted: boolean;
};

export type MixRequest = {
  tracks: MixTrackIn[];
  start_sec: number;
  end_sec: number | null;
  fade_in_sec: number;
  fade_out_sec: number;
  output_format: "mp3" | "wav";
  preview: boolean;
};

/** 믹스 주문 → 번호표. 완료되면 job.result.output_id (편집 결과와 같은 형식) */
export function createMix(req: MixRequest): Promise<Job> {
  return postJson<Job>("/api/mixes", req);
}
