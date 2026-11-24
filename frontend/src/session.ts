// 방문자 정보 (데모 모드 여부와 제한). 화면을 그리기 전에 main.tsx 가 한 번 불러 둔다.
// 이 요청과 함께 서버가 '방문자 번호표(쿠키)'를 준다 → 이후 요청은 모두 같은 번호로 묶인다.

export interface DemoLimits {
  upload_mb: number;
  media_minutes: number;
  ai_minutes: number;
  file_ttl_minutes: number;
}

export interface SessionInfo {
  demo: boolean;
  limits: DemoLimits | null;
}

let current: SessionInfo = { demo: false, limits: null };

export async function loadSession(): Promise<SessionInfo> {
  try {
    const res = await fetch("/api/session", { credentials: "same-origin" });
    if (res.ok) current = (await res.json()) as SessionInfo;
  } catch {
    /* 서버가 꺼져 있어도 화면은 뜬다 (상단 안내가 알려 준다) */
  }
  return current;
}

export const getSession = (): SessionInfo => current;
