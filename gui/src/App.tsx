import { useQuery } from '@tanstack/react-query';

import { fetchHealth, fetchVersion } from '@/lib/api';

/**
 * Phase 0 placeholder shell. Renders a single page that proves the IPC pipeline:
 * React  →  fetch  →  Python launcher.api_server.
 *
 * Real UI (sessions / bots / API configs / settings) lands in Phase 1+ as
 * separate route entries under src/features/.
 */
export function App(): JSX.Element {
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth });
  const version = useQuery({ queryKey: ['version'], queryFn: fetchVersion });

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border px-6 py-4">
        <h1 className="text-xl font-semibold">GenericAgent</h1>
        <p className="text-sm text-muted-foreground">
          Phase 0 scaffolding — feature tabs coming soon
        </p>
      </header>

      <main className="px-6 py-8 space-y-6">
        <section>
          <h2 className="font-medium mb-2">Backend health</h2>
          {health.isLoading && <p className="text-muted-foreground">…connecting</p>}
          {health.error && <p className="text-destructive">Error: {String(health.error)}</p>}
          {health.data && (
            <pre className="rounded-md bg-muted p-3 text-xs overflow-auto">
              {JSON.stringify(health.data, null, 2)}
            </pre>
          )}
        </section>

        <section>
          <h2 className="font-medium mb-2">Build info</h2>
          {version.data && (
            <p className="text-sm">
              backend v{version.data.version} · api {version.data.api}
            </p>
          )}
        </section>

        <section className="border-t border-border pt-6 text-sm text-muted-foreground space-y-1">
          <p>下一步：</p>
          <ul className="list-disc list-inside">
            <li>features/sessions — 多会话管理</li>
            <li>features/bots — 6 个聊天 bot 启停</li>
            <li>features/api-configs — Profile 切换 + 凭据 CRUD</li>
            <li>features/settings — 全局默认值</li>
            <li>每会话 API 选择（见 docs/adr/0006）</li>
          </ul>
        </section>
      </main>
    </div>
  );
}
