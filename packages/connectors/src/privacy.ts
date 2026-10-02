import { hash } from './util.ts';
import type { Json } from './types.ts';

const hiddenKeys = /^(creator_user_id|creator_account_id)$/i;
const secretKeys = /^(api_?key|access_?token|refresh_?token|authorization|password|secret)$/i;
export function redact(text: string): string {
  return text
    .replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '<redacted:private_key>')
    .replace(/(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b/g, '<redacted:api_key>')
    .replace(/Bearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}/gi, 'Bearer <redacted:token>')
    .replace(/((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[=:]\s*["']?)[^\s"'`,;}{]{8,}/gi, '$1<redacted:secret>')
    .replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/g, '$1<redacted:credentials>@');
}
/** L0 alone holds original bytes. L1/L2 never hold inline media, credentials or account identities. */
export function sanitize(value: unknown, key = '', maxBytes = 32*1024*1024, toolBudget = 8192): Json {
  if (/^(output|aggregated_output|formatted_output|stdout|stderr|result)$/.test(key)) maxBytes=Math.min(maxBytes,toolBudget);
  if (secretKeys.test(key)) return '<redacted:secret>';
  if (typeof value === 'string') {
    if (/^data:[^,]+;base64,/.test(value)) return `<attachment:sha256:${hash(value)}>`;
    if (key === 'encrypted_content') return `<opaque:sha256:${hash(value)}>`;
    const clean = redact(value);
    // Bounded copies in L1/L2; the complete native field is still addressable in L0.
    return Buffer.byteLength(clean) <= maxBytes ? clean : `${Buffer.from(clean).subarray(0,maxBytes).toString('utf8')}<truncated:sha256:${hash(value)}>`;
  }
  if (Array.isArray(value)) return value.map(item => sanitize(item,key,maxBytes,toolBudget));
  if (value !== null && typeof value === 'object') {
    const result: { [key: string]: Json } = {};
    for (const [name, item] of Object.entries(value)) {
      if (!hiddenKeys.test(name)) result[name] = sanitize(item,name,maxBytes,toolBudget);
    }
    return result;
  }
  return value === null || typeof value === 'number' || typeof value === 'boolean' ? value : null;
}
