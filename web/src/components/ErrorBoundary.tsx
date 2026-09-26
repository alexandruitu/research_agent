import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { label: string; children: ReactNode };
type State = { failed: boolean };

/** Contains a render crash to one panel so the rest of the page keeps working. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`panel "${this.props.label}" crashed`, error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="panel-error">
        <p>Something went wrong in {this.props.label}.</p>
        <button type="button" onClick={() => this.setState({ failed: false })}>Try again</button>
      </div>
    );
  }
}
