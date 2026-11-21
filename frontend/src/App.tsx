import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "./api/client";

type State =
  | { kind: "loading" }
  | { kind: "ok"; data: HealthResponse }
  | { kind: "error"; message: string };

export default function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const check = () => {
    setState({ kind: "loading" });
    getHealth()
      .then((data) => setState({ kind: "ok", data }))
      .catch((err: Error) => setState({ kind: "error", message: err.message }));
  };

  // 화면이 처음 열릴 때 한 번 서버 상태를 확인한다
  useEffect(check, []);

  return (
    <main className="app">
      <header>
        <h1>🎙️ VocalCut Studio</h1>
        <p className="sub">Step 0 · 프론트엔드 ↔ 백엔드 연결 테스트</p>
      </header>

      <section className="card">
        <h2>서버 상태</h2>
        {state.kind === "loading" && <p>확인 중…</p>}

        {state.kind === "error" && (
          <>
            <p className="bad">❌ 서버에 연결할 수 없습니다</p>
            <p className="hint">
              {state.message}
              <br />
              백엔드가 실행 중인지 확인하세요: <code>.\scripts\run-backend.ps1</code>
            </p>
          </>
        )}

        {state.kind === "ok" && (
          <ul>
            <li className="good">✅ 서버 연결됨 ({state.data.app} v{state.data.version})</li>
            <li>Python {state.data.python}</li>
            <li className={state.data.ffmpeg.available ? "good" : "bad"}>
              {state.data.ffmpeg.available
                ? `✅ FFmpeg 사용 가능 (${state.data.ffmpeg.path})`
                : "❌ FFmpeg를 찾을 수 없음 (PATH 확인, 터미널 재시작)"}
            </li>
          </ul>
        )}

        <button onClick={check}>다시 확인</button>
      </section>
    </main>
  );
}
