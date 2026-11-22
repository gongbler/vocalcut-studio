import { errorMessage, postJson } from "./errors";
import type { Job } from "./jobs";

export type SubtitleLine = { id: string; start: number; end: number; text: string };

export type Subtitles = {
  language: string;
  detected_language: string | null; // AI 가 따로 들어 보고 판단한 실제 언어
  language_mismatch: { chosen: string; detected: string } | null; // 고른 언어와 실제 언어가 다르면
  model: string;
  audio_source: "vocals" | "original";
  updated_at: number;
  segments: SubtitleLine[];
};

export type TranscriptionRequest = {
  file_id: string;
  model?: string;
  language: string; // "ko" | "en" | "ja" | "auto"
  use_vocals: boolean;
};

/** 자동 자막 주문 → 번호표. 완료되면 job.result = { file_id, lines, language } */
export function startTranscription(req: TranscriptionRequest): Promise<Job> {
  return postJson<Job>("/api/transcriptions", req);
}

/** 저장된 자막 (아직 없으면 null) */
export async function getSubtitles(fileId: string): Promise<Subtitles | null> {
  const res = await fetch(`/api/files/${fileId}/subtitles`);
  if (res.status === 404) return null;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as Subtitles;
}
