// 백엔드와 통신하는 함수들을 모아두는 곳.
// 화면 컴포넌트는 fetch 를 직접 쓰지 않고 여기 함수만 부른다.

export type HealthResponse = {
  status: string;
  app: string;
  version: string;
  python: string;
  ffmpeg: { available: boolean; path: string | null };
  separator: {
    engine: string;
    available: boolean;
    reason: string | null;
    speed_ratio: number | null; // 이 PC 실측: 걸린 시간 ÷ 곡 길이
  };
};

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/health");
  if (!res.ok) {
    throw new Error(`서버 응답 오류: HTTP ${res.status}`);
  }
  return res.json();
}
