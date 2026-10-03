import { readFileSync, existsSync, realpathSync } from 'node:fs';
import { dirname, join, resolve, basename } from 'node:path';
import { homedir } from 'node:os';
import { uid } from './util.ts';
import type { ConnectorStore } from './store.ts';

/**
 * Throwaway workspaces grouped into one "临时工作区" bucket instead of one project per directory.
 * Markers match anywhere in the path (home-relative app scratch dirs) and always win; absolute temp roots
 * only apply when the directory is not inside a Git checkout (a clone under /tmp is still that project).
 */
export const TEMPORARY_WORKSPACE_MARKERS = ['/Documents/Codex/', '/.claude/remote/'] as const;
export const TEMPORARY_WORKSPACE_PREFIXES = ['/tmp/', '/private/tmp/', '/var/folders/', '/private/var/folders/'] as const;
export function temporaryWorkspace(cwd: string, inGit = false): boolean {
  return TEMPORARY_WORKSPACE_MARKERS.some(marker=>cwd.includes(marker)) || (!inGit && TEMPORARY_WORKSPACE_PREFIXES.some(prefix=>cwd.startsWith(prefix)));
}
export function normalizeRemote(remote: string): string | null {
  let value = remote.trim().replace(/\.git\/?$/,'').replace(/\/$/,'');
  const ssh = value.match(/^[^@/]+@([^:]+):(.+)$/);
  if (ssh) value = `https://${ssh[1]}/${ssh[2]}`;
  try {
    const url = new URL(value);
    if (!url.hostname) return null;
    const path = url.pathname.replace(/^\/+|\/+$/g,'');
    return `${url.hostname.toLowerCase()}/${url.hostname.toLowerCase()==='github.com' ? path.toLowerCase() : path}`;
  } catch { return null; }
}
export function projectFor(store: ConnectorStore, cwd: string | null, recordedRemote: string | null): string | null {
  if (!cwd && !recordedRemote) return null;
  let gitRoot: string | null = null, remote: string | null = null;
  if (cwd) {
    let root = resolve(cwd);
    while (true) {
      const git = join(root,'.git');
      if (existsSync(git)) {
        try {
          let gitDir = git;
          try { const pointer = readFileSync(git,'utf8').match(/^gitdir:\s*(.+)/); if (pointer) gitDir = resolve(root,pointer[1]!); } catch { /* .git directory */ }
          let common = gitDir;
          if (existsSync(join(gitDir,'commondir'))) common = resolve(gitDir,readFileSync(join(gitDir,'commondir'),'utf8').trim());
          gitRoot = common.endsWith('/.git') ? dirname(realpathSync(common)) : root;
          const config = readFileSync(join(common,'config'),'utf8');
          remote = normalizeRemote(config.match(/\[remote "origin"\]([^[]*)/)?.[1]?.match(/^\s*url\s*=\s*(.+)$/m)?.[1] ?? '');
        } catch { gitRoot = root; }
        break;
      }
      const parent = dirname(root); if (parent === root) break; root = parent;
    }
  }
  remote ??= recordedRemote ? normalizeRemote(recordedRemote) : null;
  const temporary = cwd ? temporaryWorkspace(cwd,gitRoot!==null) : false;
  const bucket = temporary ? 'temporary' : cwd === homedir() ? 'other' : null;
  const type = bucket ? 'bucket' : remote ? 'git_remote' : gitRoot ? 'git_root' : 'path';
  const key = bucket ?? remote ?? gitRoot ?? cwd!;
  const id = uid('project',type,key);
  const previous = store.db.prepare('SELECT paths FROM project WHERE project_id=?').get(id);
  const paths = new Set<string>(previous ? JSON.parse(String(previous.paths)) as string[] : []);
  if (cwd) paths.add(cwd);
  store.db.prepare(`INSERT INTO project VALUES(?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET paths=excluded.paths`)
    .run(id,type,key,bucket==='temporary' ? '临时工作区' : bucket==='other' ? '其他' : basename(key),remote,JSON.stringify([...paths].sort()));
  return id;
}
