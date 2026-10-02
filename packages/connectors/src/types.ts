export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Obj = { [key: string]: Json };
export type Disposition = 'mapped' | 'folded' | 'replayed' | 'duplicate' | 'ignored' | 'unparsed';
export interface RawRecord {
  record_uid: string; file_id: string; generation: number; line_no: number; ordinal: number;
  byte_offset: number; byte_len: number; sha256: string; native_type: string;
  harness_version: string | null; ts: number | null; session_uid: string | null;
  turn_native_id: string | null; body: string | null; disposition: Disposition;
  ref_event_uid: string | null; note: string | null;
}
export interface StandardEvent {
  event_uid: string; session_uid: string; seq: number; ts: number; kind: string; actor: string;
  turn_uid: string | null; parent_uid: string | null; call_id: string | null;
  text: string | null; text_truncated: number; attrs: Obj; ext: Obj;
  record_uid: string; native_id: string | null;
}
export interface ParserState { meta: Obj; turn: string | null; line: number; offset: number; }
export interface Watermark extends ParserState { archived: number; }
export interface SourceFile {
  file_id: string; source_id: string; path: string; role: string; format: string; generation: number;
  dev: string | null; inode: string | null; size: number; mtime_ns: string | null;
  head_sha256: string | null; head_len: number; tail_sha256: string | null;
  watermark: string; status: string; last_scan_at: number | null;
}
export interface IngestResult {
  source_id: string; files_seen: number; files_changed: number; files_failed: number; records_added: number;
  sessions_rebuilt: number; maintenance_skipped: boolean;
  accounting: Record<string, number>; diagnostics: number;
}
export function object(value: unknown): Obj {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Obj : {};
}
export function string(value: unknown): string | null { return typeof value === 'string' ? value : null; }
export function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
export function array(value: unknown): Json[] { return Array.isArray(value) ? value as Json[] : []; }
