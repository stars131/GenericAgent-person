/**
 * Bot credentials feature — read/write whitelist of mykey fields via
 * /api/credentials. Lets users edit fs_app_id / tg_bot_token / etc. in
 * the GUI without touching mykey.py manually.
 */
import { z } from 'zod';

import { ApiError } from '@/lib/api';
import { getApiBase } from '@/lib/env';

const credValueSchema = z.union([z.string(), z.array(z.string()), z.array(z.number())]);

export const credentialsResponseSchema = z.object({
  fields: z.record(z.string(), z.array(z.string())),
  values: z.record(z.string(), z.record(z.string(), credValueSchema)),
});
export type CredentialsResponse = z.infer<typeof credentialsResponseSchema>;
export type CredValue = z.infer<typeof credValueSchema>;

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

export function getCredentials(): Promise<CredentialsResponse> {
  return request('/api/credentials', credentialsResponseSchema);
}

export function patchCredentials(
  patch: Record<string, CredValue>,
): Promise<CredentialsResponse> {
  return request('/api/credentials', credentialsResponseSchema, {
    method: 'PUT',
    body: patch,
  });
}
