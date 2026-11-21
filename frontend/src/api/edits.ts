import { errorMessage, postJson } from "./errors";
import type { Job } from "./jobs";

export type OutputFormat = "mp4" | "mp3" | "wav";

export type EditRequest = {
  source_id: string;
  start_sec: number;
  end_sec: number;
  volume_db: number;
  fade_in_sec: number;
  fade_out_sec: number;
  output_format: OutputFormat;
};

export type EditOutput = {
  id: string;
  source_id: string;
  download_name: string;
  format: OutputFormat;
  kind: "video" | "audio";
  duration_sec: number;
  size_bytes: number;
  content_url: string;
  download_url: string;
};

/** 편집 주문 → 결과물이 아니라 '번호표(Job)'를 바로 받는다 */
export function createEdit(req: EditRequest): Promise<Job> {
  return postJson<Job>("/api/edits", req);
}

export async function getOutput(id: string): Promise<EditOutput> {
  const res = await fetch(`/api/outputs/${id}`);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as EditOutput;
}
