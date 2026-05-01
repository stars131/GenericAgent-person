import { useState } from 'react';

import { useQuery } from '@tanstack/react-query';

import { fetchHealth, fetchVersion } from '@/lib/api';

import { ApiConfigsPage } from './features/api-configs';
import { BotsPage } from './features/bots';
import { SessionsPage } from './features/sessions';

type TabKey = 'sessions' | 'bots' | 'api-configs';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'sessions', label: '会话' },
  { key: 'bots', label: 'Bots' },
  { key: 'api-configs', label: 'API 配置' },
];

/**
 * Phase 1.3 main shell. Three tabs wired (sessions, bots, api-configs);
 * Settings tab arrives in 1.4. Header surfaces backend health + version,
 * tab state is local (refreshing the webview returns to "sessions").
 */
export function App(): JSX.Element {
  const [tab, setTab] = useState<TabKey>('sessions');
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

        <nav className="flex items-center gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`px-3 py-1 text-sm rounded-md ${
                tab === t.key
                  ? 'bg-accent text-accent-foreground'
                  : 'text-muted-foreground hover:bg-muted'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="text-xs text-muted-foreground">
          {health.isLoading ? '🟡 connecting' : null}
          {health.error ? '🔴 backend offline' : null}
          {health.data ? '🟢 backend ok' : null}
        </div>
      </header>

      <main className="flex-1 overflow-auto">
        {tab === 'sessions' ? <SessionsPage /> : null}
        {tab === 'bots' ? <BotsPage /> : null}
        {tab === 'api-configs' ? <ApiConfigsPage /> : null}
      </main>

      <footer className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
        下一步 tab：设置 · 详见 docs/architecture/overview.md
      </footer>
    </div>
  );
}
