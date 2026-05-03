import type { Project } from '../types';
import {
  useDeleteProject,
  usePinProject,
  useStartProject,
  useStopProject,
} from '../hooks/useSessions';

import { ApiPicker } from './ApiPicker';

interface SessionRowProps {
  project: Project;
  isActive: boolean;
  onActivate: (id: string) => void;
  onRename: (project: Project) => void;
  onShowLog: (project: Project) => void;
}

export function SessionRow({
  project,
  isActive,
  onActivate,
  onRename,
  onShowLog,
}: SessionRowProps): JSX.Element {
  const start = useStartProject();
  const stop = useStopProject();
  const pin = usePinProject();
  const del = useDeleteProject();

  const status = project.running ? '🟢 运行中' : '⚪ 已停';

  return (
    <div
      className={`rounded-lg border p-3 ${
        isActive ? 'border-primary bg-accent/30' : 'border-border'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className="text-left flex-1 min-w-0"
          onClick={() => onActivate(project.id)}
        >
          <div className="flex items-center gap-2">
            {project.pinned ? <span title="置顶">★</span> : null}
            <span className="font-medium truncate">{project.name}</span>
            <span className="text-xs text-muted-foreground">:{project.port ?? '—'}</span>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {status} · id={project.id}
          </div>
          {project.last_error ? (
            <div className="text-xs text-destructive truncate mt-0.5">{project.last_error}</div>
          ) : null}
        </button>

        <div className="flex flex-col gap-1 shrink-0">
          {project.running ? (
            <button
              type="button"
              onClick={() => stop.mutate(project.id)}
              disabled={stop.isPending}
              className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent disabled:opacity-50"
            >
              停止
            </button>
          ) : (
            <button
              type="button"
              onClick={() => start.mutate(project.id)}
              disabled={start.isPending}
              className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent disabled:opacity-50"
            >
              启动
            </button>
          )}
          {project.running && project.port ? (
            <a
              href={`http://127.0.0.1:${project.port}/`}
              target="_blank"
              rel="noreferrer"
              className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent text-center"
            >
              打开
            </a>
          ) : null}
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 flex-wrap">
        <ApiPicker project={project} />
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => onRename(project)}
            className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent"
          >
            重命名
          </button>
          <button
            type="button"
            onClick={() => onShowLog(project)}
            className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent"
          >
            日志
          </button>
          <button
            type="button"
            onClick={() => pin.mutate({ id: project.id, pinned: !project.pinned })}
            className="px-2 py-0.5 text-xs rounded border border-border hover:bg-accent"
          >
            {project.pinned ? '取消置顶' : '置顶'}
          </button>
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`删除 ${project.name}？`)) del.mutate(project.id);
            }}
            className="px-2 py-0.5 text-xs rounded border border-destructive/40 text-destructive hover:bg-destructive/10"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}
