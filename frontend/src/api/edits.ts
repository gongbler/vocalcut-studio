import { postJson } from "./errors";

export type EditRequest = {
  source_id: string;
  start_sec: number;
  end_sec: number;
  volume_db: number;
  fade_in_sec: number;
  fade_out_sec: number;
};

export type EditOutput = {
  id: string;
  source_id: string;
  download_name: string;
  kind: "video" | "audio";
  duration_sec: number;
  size_bytes: number;
  content_url: string;
};

export function createEdit(req: EditRequest): Promise<EditOutput> {
  return postJson<EditOutput>("/api/edits", req);
}
