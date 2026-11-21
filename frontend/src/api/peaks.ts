import { errorMessage } from "./errors";

export type Peaks = {
  duration_sec: number;
  peaks_per_sec: number;
  values: number[]; // 0(무음) ~ 1(최대)
};

export async function getPeaks(fileId: string): Promise<Peaks> {
  const res = await fetch(`/api/files/${fileId}/peaks`);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(body, res.status));
  return body as Peaks;
}
