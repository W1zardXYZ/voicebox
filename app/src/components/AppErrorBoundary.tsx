import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button } from '@/components/ui/button';

/**
 * Clear all persisted local state and reload the app. Use to recover from a
 * stuck/frozen UI or a rendering error.
 */
export function resetApp() {
  try {
    localStorage.clear();
  } catch {
    // ignore — localStorage may be unavailable
  }
  if (window.location.href.includes('/stories')) {
    window.location.href = '/stories';
  } else {
    window.location.reload();
  }
}

interface State {
  error: Error | null;
}

/**
 * Catches uncaught rendering errors and offers a one-click hard reset (clear
 * persisted state + reload) so the user can always get the app unstuck.
 */
export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[AppErrorBoundary] Uncaught error:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-screen items-center justify-center p-8">
          <div className="w-full max-w-md rounded-xl border bg-background p-6 text-center">
            <h2 className="text-lg font-semibold">Something went wrong</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              The app hit an unexpected error. You can reset your local state and
              reload.
            </p>
            <pre className="mt-3 max-h-40 overflow-auto rounded bg-muted/40 p-3 text-left text-[11px] whitespace-pre-wrap">
              {String(this.state.error.message || this.state.error)}
            </pre>
            <Button className="mt-4" onClick={resetApp}>
              Reset app
            </Button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
