import { Component, type ReactNode } from 'react'

/** Keeps one bad payload from unmounting the whole app. Resets when resetKey changes. */
export class ErrorBoundary extends Component<{ children: ReactNode; fallback: ReactNode; resetKey?: unknown }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: unknown) { console.error('ErrorBoundary caught', error) }
  componentDidUpdate(prev: { resetKey?: unknown }) { if (this.state.failed && prev.resetKey !== this.props.resetKey) this.setState({ failed: false }) }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}
