import { z } from 'zod';

import { ApiError } from '@/lib/api';
import { getApiBase } from '@/lib/env';

import {
  apiConfigsListSchema,
  profilesStateSchema,
  type ApiConfigEntry,
  type ApiConfigsList,
  type ProfilesState,
} from './types';

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

export function listConfigs(): Promise<ApiConfigsList> {
  return request('/api/configs', apiConfigsListSchema);
}

export function saveConfigs(configs: ApiConfigEntry[]): Promise<ApiConfigsList> {
  return request('/api/configs', apiConfigsListSchema, { method: 'PUT', body: { configs } });
}

export function getProfiles(): Promise<ProfilesState> {
  return request('/api/profiles', profilesStateSchema);
}

export function setActiveProfile(name: string | null): Promise<ProfilesState> {
  return request('/api/profiles/active', profilesStateSchema, { method: 'PUT', body: { name } });
}

export function upsertProfile(name: string, members: string[]): Promise<ProfilesState> {
  return request('/api/profiles', profilesStateSchema, {
    method: 'POST',
    body: { name, members },
  });
}

export function renameProfile(oldName: string, newName: string): Promise<ProfilesState> {
  return request(`/api/profiles/${encodeURIComponent(oldName)}`, profilesStateSchema, {
    method: 'PATCH',
    body: { new_name: newName },
  });
}

export function deleteProfile(name: string): Promise<ProfilesState> {
  return request(`/api/profiles/${encodeURIComponent(name)}`, profilesStateSchema, {
    method: 'DELETE',
  });
}
