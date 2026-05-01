import { z } from 'zod';

import { ApiError } from '@/lib/api';
import { getApiBase } from '@/lib/env';

import { settingsResponseSchema, type Settings } from './types';

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

export async function getSettings(): Promise<Settings> {
  const data = await request('/api/settings', settingsResponseSchema);
  return data.settings;
}

export async function patchSettings(patch: Partial<Settings>): Promise<Settings> {
  const data = await request('/api/settings', settingsResponseSchema, {
    method: 'PUT',
    body: patch,
  });
  return data.settings;
}
