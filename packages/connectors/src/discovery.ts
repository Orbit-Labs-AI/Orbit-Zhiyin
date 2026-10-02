import { readdir, realpath, access } from 'node:fs/promises';
import { join, resolve, relative, isAbsolute } from 'node:path';
import { homedir } from 'node:os';
import { DatabaseSync } from 'node:sqlite';
import { object, string } from './types.ts';
import type { Obj } from './types.ts';
import { maintenanceState } from './maintenance.ts';

export function defaultCodexHome(): string { return process.env.CODEX_HOME || join(homedir(),'.codex'); }
export function within(root: string, path: string): boolean {
  const value = relative(root,path);
  return value === '' || (!value.startsWith('..'+String.fromCharCode(47)) && value !== '..' && !isAbsolute(value));
}
export async function exists(path: string): Promise<boolean> { try { await access(path); return true; } catch { return false; } }
export interface Discovery { root: string; files: string[]; index_path: string | null; maintenance: boolean; maintenance_state:'held'|'idle'|'unknown'; }
export async function discoverCodex(rootPath = defaultCodexHome()): Promise<Discovery> {
  const root = await realpath(resolve(rootPath));
  const files: string[] = [];
  async function scan(directory: string): Promise<void> {
    let entries;
    try { entries = await readdir(directory,{withFileTypes:true}); }
    catch (error) { if (object(error).code === 'ENOENT') return; throw error; }
    for (const entry of entries) {
      const path = join(directory,entry.name);
      if (entry.isDirectory()) await scan(path);
      else if (entry.isFile() && /^rollout-.*\.jsonl(?:\.zst)?$/.test(entry.name)) files.push(path);
    }
  }
  await scan(join(root,'sessions')); await scan(join(root,'archived_sessions'));
  const indexes = (await readdir(root)).filter(name => /^state_\d+\.sqlite$/.test(name))
    .sort((a,b) => Number(b.match(/\d+/)?.[0])-Number(a.match(/\d+/)?.[0]));
  const state=await maintenanceState(join(root,'.tmp','rollout-maintenance.lock'));
  return { root, files:files.sort(), index_path:indexes[0] ? join(root,indexes[0]) : null,
    maintenance:state==='held',maintenance_state:state };
}
const threadColumns = ['id','rollout_path','cwd','name','title','preview','created_at','updated_at','created_at_ms','updated_at_ms',
  'archived','source','thread_source','model','model_provider','reasoning_effort','cli_version','originator',
  'git_sha','git_branch','git_origin_url','project_id','agent_nickname','agent_role','agent_path'];
/** Select only supported metadata columns. No auth/config/log databases or creator identities are read. */
export function readStateIndex(path: string): Obj[] {
  const db = new DatabaseSync(path,{readOnly:true});
  try {
    db.exec('PRAGMA query_only=ON; PRAGMA busy_timeout=3000; BEGIN');
    const tables = new Set(db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(row => row.name));
    const result: Obj[] = [];
    for (const [table,allowed,type] of [
      ['threads',threadColumns,'state_index'],
      ['thread_spawn_edges',['parent_thread_id','child_thread_id','status'],'spawn_edge'],
      ['projects',['id','name'],'project_index'],
      ['project_roots',['project_id','path','position'],'project_root']
    ] as const) {
      if (!tables.has(table)) continue;
      const columns = new Set(db.prepare(`PRAGMA table_info(${table})`).all().map(row => row.name));
      const selected = allowed.filter(column => columns.has(column));
      if (!selected.length) continue;
      for (const row of db.prepare(`SELECT ${selected.join(',')} FROM ${table}`).all()) result.push({type,payload:row as Obj});
    }
    db.exec('COMMIT'); return result;
  } finally { db.close(); }
}
export function indexThreadId(record: Obj): string | null {
  const payload = object(record.payload);
  if (!['state_index','title_index','spawn_edge','import_ledger'].includes(String(record.type))) return null;
  return string(payload.id) ?? string(payload.child_thread_id) ?? string(payload.imported_thread_id);
}
