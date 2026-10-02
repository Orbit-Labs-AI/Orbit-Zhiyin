import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { object, string, number } from './types.ts';

export function hash(value: string | Uint8Array): string {
  return createHash('sha256').update(value).digest('hex');
}
export function uid(...parts: unknown[]): string { return hash(JSON.stringify(parts)); }
export function sessionUid(source: string, native: string): string { return `codex:${uid(source).slice(0,12)}:${native}`; }
export function timestamp(value: unknown): number | null {
  if (typeof value !== 'string') return null;
  const result = Date.parse(value);
  return Number.isFinite(result) ? result : null;
}
export function durationMs(value: unknown): number | null {
  const duration = object(value);
  const seconds = number(duration.secs);
  return seconds === null ? null : Math.round(seconds * 1000 + (number(duration.nanos) ?? 0) / 1e6);
}
export function pathValue(value: unknown): string | null {
  const path = string(value);
  if (!path) return null;
  if (!path.startsWith('file://')) return path;
  try { return fileURLToPath(path); } catch { return path; }
}
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableJson(object(value)[key])}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}
