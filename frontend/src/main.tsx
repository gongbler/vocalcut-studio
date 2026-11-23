import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import "./styles/global.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* 마지막 안전망: 패널 밖(앱 전체)에서 오류가 나도 흰 화면 대신 안내 */}
    <ErrorBoundary name="앱 전체">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
