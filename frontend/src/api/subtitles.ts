import { errorMessage, postJson } from "./errors";
import type { Job } from "./jobs";

export type SubtitleLine = { id: string; start: number; end: number; text: string };

export type Subtitles = {
  language: string;
  detected_language: string | null; // AI 가 따로 들어 보고 판단한 실제 언어
  language_mismatch: { chosen: string; detected: string } | null; // 고른 언어와 실제 언어가 다르면
  model: string;
  audio_source: "vocals" | "original" | "manual"; // manual = AI 없이 손으로 만든 자막
  updated_at: number;
  edited?: boolean; // 편집기에서 고친 적이 있는지
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

/** 편집기에서 고친 자막 저장 → 서버가 정리(시간순 정렬·공백 정리)한 결과를 돌려준다 */
export async function saveSubtitles(fileId: string, segments: SubtitleLine[]): Promise<Subtitles> {
  let res: Response;
  try {
    res = await fetch(`/api/files/${fileId}/subtitles`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ segments }),
    });
  } catch {
    throw new Error("서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as Subtitles;
}
