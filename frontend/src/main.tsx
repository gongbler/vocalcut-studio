import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import { loadSession } from "./session";
import "./styles/global.css";

function render() {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      {/* 마지막 안전망: 패널 밖(앱 전체)에서 오류가 나도 흰 화면 대신 안내 */}
      <ErrorBoundary name="앱 전체">
        <App />
      </ErrorBoundary>
    </StrictMode>,
  );
}

// 화면을 그리기 전에 '방문자 번호표'부터 받는다 (데모 모드에서만 의미 있음).
// 번호표 없이 여러 요청이 동시에 나가면 요청마다 다른 번호가 생겨 파일이 흩어질 수 있다.
void loadSession().finally(render);
