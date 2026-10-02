import { DatabaseSync } from 'node:sqlite';
import { readFileSync, mkdirSync, chmodSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { uid } from './util.ts';
import type { SourceFile, RawRecord, StandardEvent } from './types.ts';

export class ConnectorStore {
  readonly db: DatabaseSync;
  readonly directory: string;
  constructor(directory: string) {
    this.directory = resolve(directory);
    mkdirSync(this.directory, { recursive: true, mode: 0o700 });
    chmodSync(this.directory,0o700);
    const path = join(this.directory,'tandem.db');
    this.db = new DatabaseSync(path);
    chmodSync(path,0o600);
    this.db.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;');
    const version = this.db.prepare('PRAGMA user_version').get()?.user_version;
    if (version === 0) {
      this.transaction(() => {
        this.db.exec(readFileSync(new URL('../schema/001.sql',import.meta.url),'utf8'));
        this.db.exec('PRAGMA user_version=1');
      });
    } else if (version !== 1) { this.db.close(); throw new Error(`Unsupported tandem.db version: ${version}`); }
    for (const suffix of ['-wal','-shm']) if (existsSync(path+suffix)) chmodSync(path+suffix,0o600);
  }
  close(): void { this.db.close(); }
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
      WHERE session_uid=? ORDER BY COALESCE(r.ts,0),r.ordinal,f.path,r.line_no`).iterate(session) as unknown as Iterable<RawRecord>;
  }
  dirty(session: string): void { this.db.prepare('INSERT OR IGNORE INTO dirty_session VALUES(?)').run(session); }
  diagnostic(source: string, code: string, message: string, file: string | null = null, record: string | null = null): void {
    this.db.prepare(`INSERT OR IGNORE INTO diagnostic VALUES(?,?,?,?,?,?,?)`)
      .run(uid(source,code,file,record,message),source,file,record,code,message,Date.now());
  }
  event(event: StandardEvent): void {
    this.db.prepare(`INSERT INTO event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      event.event_uid,event.session_uid,event.seq,event.ts,event.kind,event.actor,event.turn_uid,event.parent_uid,
      event.call_id,event.text,event.text_truncated,JSON.stringify(event.attrs),JSON.stringify(event.ext),event.record_uid,event.native_id
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
