// '내 파일' API: 목록 · 삭제 · 용량
import { errorMessage } from "./errors";

export type LibraryItem = {
  id: string;
  original_name: string;
  kind: "video" | "audio";
  duration_sec: number;
  created_at: number; // 초 단위 시각
  size_bytes: number; // 원곡 + 보컬/MR + 결과물 전체
  has_subtitles: boolean;
  stems: { vocals: string; instrumental: string } | null;
  output_count: number;
  derived_count: number;
};

export type Storage = {
  workspace_bytes: number;
  uploads_bytes: number;
  outputs_bytes: number;
  temp_bytes: number;
  models_bytes: number;
  disk_free_bytes: number;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error("서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as T;
}

export const listLibrary = () => request<LibraryItem[]>("/api/library");
export const getStorage = () => request<Storage>("/api/storage");
export const deleteLibraryItem = (id: string) =>
  request<{ deleted_files: number; deleted_outputs: number; freed_bytes: number }>(`/api/library/${id}`, {
    method: "DELETE",
  });
