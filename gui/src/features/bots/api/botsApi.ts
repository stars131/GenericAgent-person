import { z } from 'zod';

import { ApiError } from '@/lib/api';
import { getApiBase } from '@/lib/env';

import {
  botActionResponseSchema,
  botLogSchema,
  botsListSchema,
  type BotActionResponse,
  type BotLog,
  type BotsList,
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

export function listBots(): Promise<BotsList> {
  return request('/api/bots', botsListSchema);
}

export function startBot(key: string): Promise<BotActionResponse> {
  return request(`/api/bots/${encodeURIComponent(key)}/start`, botActionResponseSchema, {
    method: 'POST',
    body: {},
  });
}

export function stopBot(key: string): Promise<BotActionResponse> {
  return request(`/api/bots/${encodeURIComponent(key)}/stop`, botActionResponseSchema, {
    method: 'POST',
    body: {},
  });
}

export function getBotLog(key: string): Promise<BotLog> {
  return request(`/api/bots/${encodeURIComponent(key)}/log`, botLogSchema);
}
