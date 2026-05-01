import { useState } from 'react';

import { useQuery } from '@tanstack/react-query';

import { fetchHealth, fetchVersion } from '@/lib/api';
import { useKeyboardShortcuts, type TabKey } from '@/lib/keyboard';

import { ApiConfigsPage } from './features/api-configs';
import { BotsPage } from './features/bots';
import { SessionsPage } from './features/sessions';
import { SettingsPage } from './features/settings';
import { ThemeToggle } from './features/theme';

const TABS: { key: TabKey; label: string; hotkey: string }[] = [
  { key: 'sessions', label: '会话', hotkey: '⌘1' },
  { key: 'bots', label: 'Bots', hotkey: '⌘2' },
  { key: 'api-configs', label: 'API 配置', hotkey: '⌘3' },
  { key: 'settings', label: '设置', hotkey: '⌘4' },
];

/**
 * Phase 1 main shell + Milestone 1 polish.
 *
 * Four tabs (sessions, bots, api-configs, settings) on par with the Qt
 * launcher. Header surfaces backend health + version, theme toggle, tab
 * keyboard shortcuts (Cmd/Ctrl+1..4, Cmd/Ctrl+, , Cmd/Ctrl+/).
 */
export function App(): JSX.Element {
  const [tab, setTab] = useState<TabKey>('sessions');
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth, refetchInterval: 5000 });
  const version = useQuery({ queryKey: ['version'], queryFn: fetchVersion });

  useKeyboardShortcuts(setTab);

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <header className="border-b border-border px-4 py-3 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-base font-semibold">GenericAgent</h1>
          {version.data ? (
            <p className="text-xs text-muted-foreground truncate">
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
              title={`${t.label}  (${t.hotkey})`}
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

        <div className="flex items-center gap-2">
          <ThemeToggle />
          <span className="text-xs text-muted-foreground" title="Cmd/Ctrl+/ 查看快捷键">
            {health.isLoading ? '🟡 connecting' : null}
            {health.error ? '🔴 backend offline' : null}
            {health.data ? '🟢 backend ok' : null}
          </span>
        </div>
      </header>

      <main className="flex-1 overflow-auto">
        {tab === 'sessions' ? <SessionsPage /> : null}
        {tab === 'bots' ? <BotsPage /> : null}
        {tab === 'api-configs' ? <ApiConfigsPage /> : null}
        {tab === 'settings' ? <SettingsPage /> : null}
      </main>
    </div>
  );
}
