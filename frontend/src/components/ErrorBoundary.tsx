import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  /** 어느 부분인지 (안내 문구에 표시) */
  name: string;
  children: ReactNode;
};

type State = { error: Error | null };

/**
 * 화면의 한 부분(패널)에서 오류가 나도 '그 부분만' 안내로 바꾸고 나머지 화면은 계속 쓰게 한다.
 *
 * React 는 그리는 도중 오류가 나면 기본적으로 화면 전체를 지운다(흰 화면).
 * 오류 경계(Error Boundary)로 감싸면 그 안의 오류를 여기서 받아, 감싼 부분만 대신 그린다.
 * ⚠️ 오류 경계는 아직 함수형 컴포넌트로 만들 수 없어서 class 로 만든다 (React 의 규칙).
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 개발자 도구(F12) 콘솔에 자세한 위치를 남긴다
    console.error(`[${this.props.name}] 화면 오류`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="card crash" role="alert">
        <h2>⚠️ {this.props.name}에서 화면 오류가 났어요</h2>
        <p className="hint">
          다른 부분은 그대로 쓸 수 있어요. 아래 버튼으로 이 부분만 다시 그려 보고, 계속 안 되면 새로고침(F5)하세요.
          저장된 파일·자막은 지워지지 않아요.
        </p>
        <details>
          <summary className="hint">자세한 내용 (문제 보고용)</summary>
          <code className="crash-detail">{this.state.error.message}</code>
        </details>
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={() => this.setState({ error: null })}>🔄 이 부분 다시 그리기</button>
          <button className="secondary" onClick={() => location.reload()}>
            새로고침
          </button>
        </div>
      </section>
    );
  }
}
