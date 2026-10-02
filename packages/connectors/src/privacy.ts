import { hash } from './util.ts';
import type { Json } from './types.ts';

const hiddenKeys = /^(creator_user_id|creator_account_id)$/i;
function secretKey(key:string):boolean {
  const normalized=key.replace(/([a-z0-9])([A-Z])/g,'$1_$2').toLowerCase().replace(/[^a-z0-9]+/g,'_');
  // Do not match plural token counters or token_usage objects. Credentials may use vendor prefixes and camelCase.
  return /(?:^|_)(?:api_?key|private_?key|signing_?key|token|authorization|credentials?|cookies?|set_cookie)$/.test(normalized)
    || /(?:^|_)(?:secret|password|passwd)(?:_|$)/.test(normalized);
}
export function redact(text: string): string {
  return text
    .replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '<redacted:private_key>')
    .replace(/(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b/g, '<redacted:api_key>')
    .replace(/Bearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}/gi, 'Bearer <redacted:token>')
    .replace(/Basic\s+[A-Za-z0-9+/]{4,}={0,2}/gi, 'Basic <redacted:credentials>')
    .replace(/((?:Proxy-)?Authorization\s*:\s*)[^\r\n]+/gi,'$1<redacted:authorization>')
    .replace(/((?:Cookie|Set-Cookie)\s*:\s*)[^\r\n]+/gi,'$1<redacted:cookie>')
    .replace(/((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[=:]\s*["']?)[^\s"'`,;}{]{8,}/gi, '$1<redacted:secret>')
    .replace(/\b([a-z][a-z0-9+.-]*:\/\/)[^\s/@:]+(?::[^\s/@]*)?@/gi, '$1<redacted:credentials>@');
}
/** L0 alone holds original bytes. L1/L2 never hold inline media, credentials or account identities. */
export function sanitize(value: unknown, key = '', maxBytes = 32*1024*1024, toolBudget = 8192): Json {
  if (/^(output|aggregated_output|formatted_output|stdout|stderr|result)$/.test(key)) maxBytes=Math.min(maxBytes,toolBudget);
  if (secretKey(key)) return '<redacted:secret>';
  if (typeof value === 'string') {
    if (/^\s*[\[{]/.test(value)) {
      try {
        const parsed=JSON.parse(value);
        const cleaned=sanitize(parsed,'',maxBytes,toolBudget);
        if (JSON.stringify(parsed)!==JSON.stringify(cleaned)) return JSON.stringify(cleaned);
      } catch { /* Non-JSON text follows the normal string redaction path. */ }
    }
    if (/^data:[^,]+;base64,/.test(value)) return `<attachment:sha256:${hash(value)}>`;
    if (key === 'encrypted_content') return /^<opaque:sha256:[0-9a-f]{64}>$/.test(value)?value:`<opaque:sha256:${hash(value)}>`;
    const clean = redact(value);
    if (/<truncated:sha256:[0-9a-f]{64}>$/.test(clean)) return clean;
    // Bounded copies in L1/L2; the complete native field is still addressable in L0.
    return Buffer.byteLength(clean) <= maxBytes ? clean : `${Buffer.from(clean).subarray(0,maxBytes).toString('utf8')}<truncated:sha256:${hash(value)}>`;
  }
  if (Array.isArray(value)) return value.map(item => sanitize(item,key,maxBytes,toolBudget));
  if (value !== null && typeof value === 'object') {
    const result: { [key: string]: Json } = {};
    const native=value as Record<string,unknown>;
    const imageGeneration=['image_generation_call','ImageGeneration'].includes(String(native.type))||native.kind==='image_gen.generation';
    for (const [name, item] of Object.entries(value)) {
      if((name==='b64_json'||(imageGeneration&&name==='result'))&&typeof item==='string') {result[name]=/^<attachment:sha256:[0-9a-f]{64}>$/.test(item)?item:`<attachment:sha256:${hash(item)}>`;continue;}
      if (!hiddenKeys.test(name)) result[name] = sanitize(item,name,maxBytes,toolBudget);
    }
    return result;
  }
  return value === null || typeof value === 'number' || typeof value === 'boolean' ? value : null;
}
