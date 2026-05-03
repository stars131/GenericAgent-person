/**
 * Typed wrappers over the Phase 1 endpoints in launcher/api_server.py.
 */
import { z } from 'zod';

import { ApiError } from '@/lib/api';
import { getApiBase } from '@/lib/env';

import {
  configsListSchema,
  profilesStateSchema,
  projectSchema,
  projectsListSchema,
  type ApiConfig,
  type Project,
  type ProfilesState,
  type ProjectsList,
} from '../types';

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit & { body?: unknown },
): Promise<T> {
  const url = `${getApiBase()}${path}`;
  const fetchInit: RequestInit = {
    headers: { 'content-type': 'application/json' },
    ...init,
  };
  if (init?.body !== undefined && typeof init.body !== 'string') {
    fetchInit.body = JSON.stringify(init.body);
  }
  const res = await fetch(url, fetchInit);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiError(`HTTP ${res.status} on ${path}: ${body.slice(0, 200)}`, res.status, url);
  }
  const json = (await res.json()) as unknown;
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError(`Invalid response from ${path}: ${parsed.error.message}`, res.status, url);
  }
  return parsed.data;
}

const singleProjectSchema = z.object({ project: projectSchema });

export function listProjects(): Promise<ProjectsList> {
  return request('/api/projects', projectsListSchema);
}

export async function createProject(name: string): Promise<Project> {
  const data = await request('/api/projects', singleProjectSchema, {
    method: 'POST',
    body: { name },
  });
  return data.project;
}

export async function deleteProject(id: string): Promise<void> {
  await request(`/api/projects/${encodeURIComponent(id)}`, z.object({ deleted: z.string() }), {
    method: 'DELETE',
  });
}

export async function startProject(id: string): Promise<Project> {
  const data = await request(
    `/api/projects/${encodeURIComponent(id)}/start`,
    singleProjectSchema,
    { method: 'POST', body: {} },
  );
  return data.project;
}

export async function stopProject(id: string): Promise<Project> {
  const data = await request(
    `/api/projects/${encodeURIComponent(id)}/stop`,
    singleProjectSchema,
    { method: 'POST', body: {} },
  );
  return data.project;
}

export async function renameProject(id: string, name: string): Promise<Project> {
  const data = await request(
    `/api/projects/${encodeURIComponent(id)}`,
    singleProjectSchema,
    { method: 'PATCH', body: { name } },
  );
  return data.project;
}

export async function pinProject(id: string, pinned: boolean): Promise<Project> {
  const data = await request(
    `/api/projects/${encodeURIComponent(id)}/pin`,
    singleProjectSchema,
    { method: 'POST', body: { pinned } },
  );
  return data.project;
}

export async function activateProject(id: string): Promise<Project> {
  const data = await request(
    `/api/projects/${encodeURIComponent(id)}/activate`,
    singleProjectSchema,
    { method: 'POST', body: {} },
  );
  return data.project;
}

export async function setProjectLlm(
  id: string,
  payload: { config_name?: string; llm_no?: number },
): Promise<Project> {
  const data = await request(
    `/api/projects/${encodeURIComponent(id)}/llm`,
    singleProjectSchema,
    { method: 'PUT', body: payload },
  );
  return data.project;
}

export async function listApiConfigs(): Promise<ApiConfig[]> {
  const data = await request('/api/configs', configsListSchema);
  return data.configs;
}

export function getProfiles(): Promise<ProfilesState> {
  return request('/api/profiles', profilesStateSchema);
}
