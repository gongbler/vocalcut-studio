// 서버 상태를 앱 전체가 '하나의 창구'로 공유한다.
//
// 예전에는 패널마다 열릴 때 한 번씩 서버에 물어봐서, 그 순간 서버가 꺼져 있으면
// 서버를 다시 켜도 패널이 계속 "사용할 수 없음"으로 남았다.
// 이제는 여기서 주기적으로 확인하고(꺼져 있으면 3초마다, 켜져 있으면 10초마다),
// 상태가 바뀌면 이 훅을 쓰는 모든 화면이 자동으로 다시 그려진다.
import { useSyncExternalStore } from "react";
import { getHealth, type HealthResponse } from "../api/client";

export type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; data: HealthResponse }
  | { kind: "offline"; message: string };

let state: HealthState = { kind: "loading" };
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setTimeout> | null = null;
let inflight = false;

function set(next: HealthState) {
  state = next;
  listeners.forEach((l) => l());
}

/** 지금 바로 다시 확인 (새로고침 버튼 · 주기 확인에서 사용) */
export async function refreshHealth(): Promise<void> {
  if (inflight) return;
  inflight = true;
  try {
    set({ kind: "ok", data: await getHealth() });
  } catch (err) {
    set({ kind: "offline", message: (err as Error).message });
  } finally {
    inflight = false;
    schedule();
  }
}

function schedule() {
  if (timer) clearTimeout(timer);
  if (listeners.size === 0) return; // 보는 화면이 없으면 쉬기
  timer = setTimeout(refreshHealth, state.kind === "ok" ? 10_000 : 3_000);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) void refreshHealth(); // 첫 구독자가 생기면 확인 시작
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer) clearTimeout(timer);
  };
}

export function useHealth(): HealthState {
  return useSyncExternalStore(subscribe, () => state);
}
