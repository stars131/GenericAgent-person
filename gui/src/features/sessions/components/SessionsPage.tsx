import { useState } from 'react';

import type { Project } from '../types';
import {
  useActivateProject,
  useCreateProject,
  useProjects,
  useRenameProject,
} from '../hooks/useSessions';

import { SessionRow } from './SessionRow';

export function SessionsPage(): JSX.Element {
  const projects = useProjects();
  const create = useCreateProject();
  const activate = useActivateProject();
  const rename = useRenameProject();

  const [newName, setNewName] = useState('');

  const onCreate = (e: React.FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    create.mutate(name, {
      onSuccess: () => setNewName(''),
    });
  };

  const onRename = (project: Project) => {
    const next = window.prompt('新名称：', project.name);
    if (next && next.trim() && next !== project.name) {
      rename.mutate({ id: project.id, name: next.trim() });
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4 max-w-3xl mx-auto">
      <header>
        <h1 className="text-xl font-semibold">会话</h1>
        <p className="text-sm text-muted-foreground">
          多会话同时运行；每个会话可单独选 API 配置（ADR-0006）。
        </p>
      </header>

      <form onSubmit={onCreate} className="flex gap-2">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="新会话名称"
          className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm"
        />
        <button
          type="submit"
          disabled={!newName.trim() || create.isPending}
          className="rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm hover:bg-primary/90 disabled:opacity-50"
        >
          新建
        </button>
      </form>

      {projects.isLoading ? <p className="text-muted-foreground">加载中…</p> : null}
      {projects.error ? (
        <p className="text-destructive text-sm">
          后端连接失败：{String(projects.error)}
        </p>
      ) : null}

      {projects.data ? (
        <ul className="flex flex-col gap-2">
          {projects.data.projects.length === 0 ? (
            <li className="text-sm text-muted-foreground italic">暂无会话，先在上面新建一个。</li>
          ) : null}
          {projects.data.projects.map((p) => (
            <li key={p.id}>
              <SessionRow
                project={p}
                isActive={p.id === projects.data.active_id}
                onActivate={(id) => activate.mutate(id)}
                onRename={onRename}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
