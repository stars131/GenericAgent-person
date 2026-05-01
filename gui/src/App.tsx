import { useQuery } from '@tanstack/react-query';

import { fetchHealth, fetchVersion } from '@/lib/api';

import { SessionsPage } from './features/sessions';

/**
 * Phase 1.1 main shell. Renders the Sessions page; a real router with
 * additional tabs (Bots / API configs / Settings) lands in subsequent
 * commits. Until then a small "backend status" footer surfaces /api/health
 * + /api/version so we always know the IPC pipeline is alive.
 */
export function App(): JSX.Element {
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth, refetchInterval: 5000 });
  const version = useQuery({ queryKey: ['version'], queryFn: fetchVersion });

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <header className="border-b border-border px-4 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold">GenericAgent</h1>
          {version.data ? (
            <p className="text-xs text-muted-foreground">
              v{version.data.version} · api {version.data.api} · py{version.data.python}
            </p>
          ) : null}
        </div>
        <div className="text-xs text-muted-foreground">
          {health.isLoading ? '🟡 connecting' : null}
          {health.error ? '🔴 backend offline' : null}
          {health.data ? '🟢 backend ok' : null}
        </div>
      </header>

      <main className="flex-1 overflow-auto">
        <SessionsPage />
      </main>

      <footer className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
        下一步 tab：Bots / API 配置 / 设置 · 详见 docs/architecture/overview.md
      </footer>
    </div>
  );
}
