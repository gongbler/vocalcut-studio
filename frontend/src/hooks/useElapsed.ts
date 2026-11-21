import { useEffect, useState } from "react";

/** running 이 true 인 동안 1초마다 1씩 늘어나는 경과 시간(초). false → true 가 되면 0부터 다시. */
export function useElapsed(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) return;
    setElapsed(0);
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(timer); // 정리: 끝나면 타이머 해제
  }, [running]);
  return elapsed;
}
