import { DatabaseSync } from 'node:sqlite';
import { readFileSync, mkdirSync, chmodSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { uid } from './util.ts';
import type { SourceFile, RawRecord, StandardEvent } from './types.ts';
import { rebuildSource } from './normalize.ts';
import { sanitize } from './privacy.ts';

/** Bump when redact()/sanitize() change (re-cleans cached L1) or when L2/L3 derivation changes (rebuilds). */
export const SCHEMA_VERSION=3;
export const REDACTION_VERSION='codex-redact/0.2.4', DERIVATION_VERSION='codex-derive/0.2.5';
export class ConnectorStore {
  readonly db: DatabaseSync;
  readonly directory: string;
  constructor(directory: string) {
    this.directory = resolve(directory);
    mkdirSync(this.directory, { recursive: true, mode: 0o700 });
    chmodSync(this.directory,0o700);
    const path = join(this.directory,'orbit.db');
    this.db = new DatabaseSync(path);
    const present=new Set(this.db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(row=>row.name));
    const initialVersion=this.db.prepare('PRAGMA user_version').get()?.user_version;
    if ((initialVersion===0&&present.size>0)||(initialVersion!==0&&!present.has('archive_chunk'))) {
      this.db.close(); throw new Error('This is not a Codex Connector staging database; use a separate data directory and the orbit-data bridge');
    }
    chmodSync(path,0o600);
    this.db.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;');
    const version = this.db.prepare('PRAGMA user_version').get()?.user_version;
    if (version === 0) {
      this.transaction(() => {
        this.db.exec(readFileSync(new URL('../schema/001.sql',import.meta.url),'utf8'));
        this.db.exec('PRAGMA user_version=1');
      });
    } else if (version !== 1 && version !== 2 && version !== SCHEMA_VERSION) { this.db.close(); throw new Error(`Unsupported orbit.db version: ${version}`); }
    const migrated=version!==SCHEMA_VERSION;
    if (version===0||version===1) {
      this.transaction(()=>{
        this.db.exec(readFileSync(new URL('../schema/002.sql',import.meta.url),'utf8'));
        this.db.exec('PRAGMA user_version=2');
      });
    }
    if (migrated) {
      this.transaction(()=>{
        this.db.exec(readFileSync(new URL('../schema/003.sql',import.meta.url),'utf8'));
        this.db.exec(`PRAGMA user_version=${SCHEMA_VERSION}`);
      });
    }
    const redaction=this.db.prepare("SELECT version FROM pipeline_version WHERE component='redaction'").get()?.version;
    const derivation=this.db.prepare("SELECT version FROM pipeline_version WHERE component='derivation'").get()?.version;
    if (migrated||redaction!==REDACTION_VERSION||derivation!==DERIVATION_VERSION) {
      this.transaction(()=>{
        if(migrated||redaction!==REDACTION_VERSION) for (const row of this.db.prepare('SELECT record_uid,body FROM raw_record WHERE body IS NOT NULL').iterate()) {
            this.db.prepare('UPDATE raw_record SET body=? WHERE record_uid=?').run(JSON.stringify(sanitize(JSON.parse(String(row.body)))),String(row.record_uid));
          }
        this.db.prepare("UPDATE pipeline_version SET version=? WHERE component='redaction'").run(REDACTION_VERSION);
        this.db.prepare("UPDATE pipeline_version SET version=? WHERE component='derivation'").run(DERIVATION_VERSION);
        this.db.prepare("UPDATE pipeline_version SET version='codex-connector/0.2.1' WHERE component='parser'").run();
        this.db.prepare('INSERT OR IGNORE INTO dirty_session SELECT DISTINCT session_uid FROM current_record WHERE session_uid IS NOT NULL').run();
      });
      for (const source of this.db.prepare('SELECT source_id FROM source').all()) rebuildSource(this,String(source.source_id));
    }
    this.db.exec('PRAGMA application_id=1413697358');
    for (const suffix of ['-wal','-shm']) if (existsSync(path+suffix)) chmodSync(path+suffix,0o600);
  }
  close(): void { this.db.close(); }
  rebuild(): number {
    this.db.prepare('INSERT OR IGNORE INTO dirty_session SELECT DISTINCT session_uid FROM current_record WHERE session_uid IS NOT NULL').run();
    let rebuilt=0;
    for (const source of this.db.prepare('SELECT source_id FROM source').all()) rebuilt+=rebuildSource(this,String(source.source_id));
    return rebuilt;
  }
  transaction<T>(action: () => T): T {
    this.db.exec('BEGIN IMMEDIATE');
    try { const result = action(); this.db.exec('COMMIT'); return result; }
    catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
  file(id: string): SourceFile | undefined {
    return this.db.prepare('SELECT * FROM source_file WHERE file_id=?').get(id) as unknown as SourceFile | undefined;
  }
  records(session: string): Iterable<RawRecord> {
    return this.db.prepare(`SELECT r.* FROM current_record r JOIN source_file f USING(file_id)
      WHERE session_uid=? ORDER BY CASE WHEN f.role='transcript' THEN 0 ELSE 1 END,r.ordinal,f.path,r.line_no`).iterate(session) as unknown as Iterable<RawRecord>;
  }
  dirty(session: string): void { this.db.prepare('INSERT OR IGNORE INTO dirty_session VALUES(?)').run(session); }
  diagnostic(source: string, code: string, message: string, file: string | null = null, record: string | null = null): void {
    this.db.prepare(`INSERT OR IGNORE INTO diagnostic VALUES(?,?,?,?,?,?,?)`)
      .run(uid(source,code,file,record,message),source,file,record,code,message,Date.now());
  }
  event(event: StandardEvent): void {
    this.db.prepare(`INSERT INTO event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      event.event_uid,event.session_uid,event.seq,event.ts,event.kind,event.actor,event.turn_uid,event.parent_uid,
      event.call_id,event.text,event.text_truncated,JSON.stringify(event.attrs),JSON.stringify(event.ext),event.record_uid,event.native_id,
      JSON.stringify(event.native_key),event.event_path,event.contract_version,event.mapper_version
    );
  }
  accounting(source: string): Record<string,number> {
    const result: Record<string,number> = {};
    const rows = this.db.prepare(`SELECT disposition,count(*) AS n FROM current_record r JOIN source_file f USING(file_id)
      WHERE f.source_id=? GROUP BY disposition`).all(source);
    for (const row of rows) result[String(row.disposition)] = Number(row.n);
    return result;
  }
}
