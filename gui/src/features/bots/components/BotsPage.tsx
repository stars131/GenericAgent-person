import { useState } from 'react';

import { useBotLog } from '../hooks/useBots';

interface BotLogDrawerProps {
  botKey: string;
  onClose: () => void;
}

export function BotLogDrawer({ botKey, onClose }: BotLogDrawerProps): JSX.Element {
  const { data, isLoading, error, refetch } = useBotLog(botKey);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl h-2/3 rounded-t-lg border border-border bg-background flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <div>
            <h3 className="font-medium">日志：{botKey}</h3>
            {data?.path ? (
              <p className="text-xs text-muted-foreground">{data.path}</p>
            ) : null}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void refetch()}
              className="px-2 py-1 text-xs rounded border border-border hover:bg-accent"
            >
              刷新
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-2 py-1 text-xs rounded border border-border hover:bg-accent"
            >
              关闭
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto bg-muted/40 p-3 font-mono text-xs">
          {isLoading ? <p className="text-muted-foreground">加载中…</p> : null}
          {error ? <p className="text-destructive">{String(error)}</p> : null}
          {data && !data.exists ? (
            <p className="text-muted-foreground">日志文件还不存在（bot 尚未运行）。</p>
          ) : null}
          {data?.lines.length === 0 && data.exists ? (
            <p className="text-muted-foreground">空文件。</p>
          ) : null}
          {data?.lines.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              {line}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

interface BotsPageProps {}

export function BotsPage(_props: BotsPageProps = {}): JSX.Element {
  const [logKey, setLogKey] = useState<string | null>(null);
  return (
    <>
      <BotsTable onShowLog={(k) => setLogKey(k)} />
      {logKey ? <BotLogDrawer botKey={logKey} onClose={() => setLogKey(null)} /> : null}
    </>
  );
}

import { useBots, useStartBot, useStopBot } from '../hooks/useBots';

interface BotsTableProps {
  onShowLog: (key: string) => void;
}

function BotsTable({ onShowLog }: BotsTableProps): JSX.Element {
  const bots = useBots();
  const start = useStartBot();
  const stop = useStopBot();

  return (
    <div className="flex flex-col gap-4 p-4 max-w-3xl mx-auto">
      <header>
        <h1 className="text-xl font-semibold">Bots</h1>
        <p className="text-sm text-muted-foreground">
          每 3 秒刷新；🟢 本 launcher / 🟡 外部进程 / ⚪ 已停。配置编辑请改 mykey.py。
        </p>
      </header>

      {bots.isLoading ? <p className="text-muted-foreground">加载中…</p> : null}
      {bots.error ? (
        <p className="text-destructive text-sm">后端连接失败：{String(bots.error)}</p>
      ) : null}

      {bots.data ? (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-left border-b border-border">
              <th className="py-2 px-2">Bot</th>
              <th className="py-2 px-2">配置</th>
              <th className="py-2 px-2">状态</th>
              <th className="py-2 px-2 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {bots.data.bots.map((bot) => {
              let cfgText = '✅';
              let cfgTip = '已配置';
              if (!bot.configured) {
                cfgText = '❌';
                cfgTip = '缺字段: ' + bot.missing_fields.join(', ');
              } else if (!bot.sdk_installed) {
                cfgText = '⚠️';
                cfgTip = '缺 SDK: ' + bot.missing_modules.join(', ');
              }
              const stateText = bot.running_self
                ? '🟢 运行中（本 launcher）'
                : bot.running_external
                  ? '🟡 外部进程占端口'
                  : '⚪ 已停';
              const startable = bot.configured && bot.sdk_installed && !bot.running;
              return (
                <tr key={bot.key} className="border-b border-border last:border-0">
                  <td className="py-2 px-2">
                    <div className="font-medium">{bot.display_name}</div>
                    <div className="text-xs text-muted-foreground">{bot.key}</div>
                  </td>
                  <td className="py-2 px-2" title={cfgTip}>{cfgText}</td>
                  <td className="py-2 px-2">{stateText}</td>
                  <td className="py-2 px-2 text-right">
                    <div className="inline-flex gap-1">
                      <button
                        type="button"
                        onClick={() => start.mutate(bot.key)}
                        disabled={!startable || start.isPending}
                        className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent disabled:opacity-40"
                      >
                        启动
                      </button>
                      <button
                        type="button"
                        onClick={() => stop.mutate(bot.key)}
                        disabled={!bot.running_self || stop.isPending}
                        className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent disabled:opacity-40"
                      >
                        停止
                      </button>
                      <button
                        type="button"
                        onClick={() => onShowLog(bot.key)}
                        className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent"
                      >
                        日志
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}

      {start.isError ? (
        <p className="text-xs text-destructive">启动失败：{String(start.error)}</p>
      ) : null}
    </div>
  );
}
