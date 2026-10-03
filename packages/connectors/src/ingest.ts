import { open, stat, readFile, realpath } from 'node:fs/promises';
import { realpathSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { hash, uid, sessionUid, timestamp, stableJson } from './util.ts';
import { object, string, number, array } from './types.ts';
import type { Obj, Watermark, SourceFile, RawRecord, IngestResult } from './types.ts';
import { sanitize } from './privacy.ts';
import { linesFromStream } from './lines.ts';
import { Readable } from 'node:stream';
import { decompressFrames } from './zstd.ts';
import type { Line } from './lines.ts';
import { archiveRange, archiveBuffer,archivedBytes,archiveRangeHash } from './archive.ts';
import { discoverCodex, exists, readStateIndex, indexThreadId, within } from './discovery.ts';
import { ConnectorStore } from './store.ts';
import { rebuildSource } from './normalize.ts';

const emptyWatermark = (): Watermark => ({meta:{},turn:null,line:0,offset:0,archived:0});
export interface IngestOptions { files?: string[]; includeMetadata?: boolean; }
async function rangeHash(path: string, start: number, length: number): Promise<string> {
  const handle = await open(path,'r');
  try { const bytes = Buffer.alloc(length); const {bytesRead} = await handle.read(bytes,0,length,start); return hash(bytes.subarray(0,bytesRead)); }
  finally { await handle.close(); }
}
export class CodexConnector {
  readonly store: ConnectorStore;
  readonly root: string;
  readonly sourceId: string;
  private running = false;
  constructor(store: ConnectorStore, root: string) {
    this.store = store; this.root = realpathSync(resolve(root)); this.sourceId = `codex:${uid(this.root).slice(0,20)}`;
    if (within(this.root,realpathSync(store.directory))) throw new Error('Orbit data directory must be outside CODEX_HOME');
    store.db.prepare('INSERT OR IGNORE INTO source VALUES(?,?,?,?,?,?)')
      .run(this.sourceId,'codex',this.root,basename(this.root),1,Date.now());
  }
  async ingest(options: IngestOptions = {}): Promise<IngestResult> {
    if (this.running) throw new Error('An ingest is already running for this connector');
    this.running = true;
    const result: IngestResult = {source_id:this.sourceId,files_seen:0,files_changed:0,files_failed:0,records_added:0,sessions_rebuilt:0,
      maintenance_skipped:false,accounting:{},diagnostics:0};
    try {
      const discovery = await discoverCodex(this.root);
      if (discovery.root !== this.root) throw new Error('Pass the canonical CODEX_HOME path (resolve symlinks first)');
      if (discovery.maintenance) { result.maintenance_skipped = true; return result; }
      if (discovery.maintenance_state==='unknown') this.store.diagnostic(this.sourceId,'maintenance_state_unavailable','OS lock ownership unavailable; file consistency guards remain active');
      const seen = new Set<string>();
      const selection=options.files===undefined?null:new Set(await Promise.all(options.files.map(async path=>{
        const canonical=await realpath(resolve(this.root,path));
        if (!within(this.root,canonical) || !/^rollout-.*\.jsonl(?:\.zst)?$/.test(basename(canonical))) throw new Error('Selected file must be a Codex rollout within CODEX_HOME');
        return canonical;
      })));
      if (discovery.index_path && options.includeMetadata!==false) {
        seen.add(uid(this.sourceId,'index_db'));
        try {
          if (!within(this.root,await realpath(discovery.index_path))) throw new Error('Index is outside CODEX_HOME');
          const records = readStateIndex(discovery.index_path);
          const id = await this.snapshot(discovery.index_path,'index_db',records,result); seen.add(id);
          for (const record of records) {
            const path = string(object(record.payload).rollout_path);
            if (path && within(this.root,resolve(this.root,path)) && /^rollout-.*\.jsonl(?:\.zst)?$/.test(basename(path)) && await exists(resolve(this.root,path))) {
              const canonical = await realpath(resolve(this.root,path));
              if (within(this.root,canonical)) discovery.files.push(canonical);
            }
          }
        } catch { result.files_failed++; this.store.diagnostic(this.sourceId,'index_unavailable','State index could not be read consistently; transcripts remain usable'); }
      }
      const ledgerPath = join(this.root,'external_agent_session_imports.json');
      if (options.includeMetadata!==false && await exists(ledgerPath)) {
        seen.add(uid(this.sourceId,'import_ledger'));
        try {
          if (!within(this.root,await realpath(ledgerPath))) throw new Error('Ledger is outside CODEX_HOME');
          const bytes = await readFile(ledgerPath);
          if (bytes.length > 16*1024*1024) throw new Error('Import ledger is too large');
          const ledger = object(JSON.parse(bytes.toString('utf8')));
          const records = array(ledger.records).map(payload => ({type:'import_ledger',payload}) as Obj);
          const id = await this.snapshot(ledgerPath,'import_ledger',records,result,bytes); seen.add(id);
        } catch { result.files_failed++; this.store.diagnostic(this.sourceId,'ledger_unavailable','External import ledger is invalid or unreadable'); }
      }
      const titleIndex = join(this.root,'session_index.jsonl');
      if (options.includeMetadata!==false && await exists(titleIndex)) {
        const id = uid(this.sourceId,'title-index'); seen.add(id);
        if (within(this.root,await realpath(titleIndex))) await this.transcript(titleIndex,id,'title_index',result);
        else { result.files_failed++; this.store.diagnostic(this.sourceId,'title_index_unavailable','Title index is outside CODEX_HOME'); }
      }
      // Movement and compression preserve the logical file identity. Prefer the live JSONL if a maintenance copy coexists.
      const files = new Map<string,string>();
      for (const path of new Set(discovery.files)) {
        if (selection && !selection.has(path)) continue;
        const id = uid(this.sourceId,'rollout',basename(path).replace(/\.zst$/,''));
        if (!files.has(id) || !path.endsWith('.zst')) files.set(id,path);
      }
      for (const [id,path] of files) { seen.add(id); await this.transcript(path,id,'transcript',result); }
      this.store.transaction(() => {
        const files = this.store.db.prepare('SELECT file_id FROM source_file WHERE source_id=?').all(this.sourceId);
        for (const file of files) if (!seen.has(String(file.file_id))) {
          const prior=this.store.file(String(file.file_id))!;
          if (!selection && (options.includeMetadata!==false||prior.role==='transcript')) this.store.db.prepare("UPDATE source_file SET status='gone_upstream' WHERE file_id=?").run(file.file_id!);
        }
        this.store.db.prepare('INSERT INTO source_boundary VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET last_ingest_scope=excluded.last_ingest_scope,observed_at=excluded.observed_at')
          .run(this.sourceId,JSON.stringify({root:this.root,selected_files:selection?[...selection].sort():null,metadata:options.includeMetadata===false?'excluded':'included',selection_only_affects_this_read:true}),Date.now());
      });
      result.sessions_rebuilt = rebuildSource(this.store,this.sourceId);
      result.accounting = this.store.accounting(this.sourceId);
      result.diagnostics = Number(this.store.db.prepare('SELECT count(*) AS n FROM diagnostic WHERE source_id=?').get(this.sourceId)?.n);
      return result;
    } finally { this.running = false; }
  }
  private ensureFile(path: string, id: string, role: string, format: string): SourceFile {
    this.store.db.prepare(`INSERT OR IGNORE INTO source_file(file_id,source_id,path,role,format) VALUES(?,?,?,?,?)`)
      .run(id,this.sourceId,path,role,format);
    return this.store.file(id)!;
  }
  private markOldSessions(id: string): void {
    for (const row of this.store.db.prepare('SELECT DISTINCT session_uid FROM current_record WHERE file_id=? AND session_uid IS NOT NULL').all(id)) {
      this.store.dirty(String(row.session_uid));
    }
  }
  private async transcript(path: string, id: string, role: string, result: IngestResult): Promise<void> {
    result.files_seen++;
    const format = path.endsWith('.zst') ? 'jsonl_zstd' : 'jsonl';
    const previous = this.ensureFile(path,id,role,format);
    try {
      const info = await stat(path,{bigint:true});
      const size = Number(info.size);
      const old = JSON.parse(previous.watermark) as Watermark;
      const unchanged = previous.inode === String(info.ino) && previous.dev === String(info.dev) && previous.size === size
        && previous.mtime_ns === String(info.mtimeNs) && previous.format === format;
      if (unchanged) {
        this.store.db.prepare("UPDATE source_file SET path=?,status='active' WHERE file_id=?").run(path,id);
        return;
      }
      const headMatches = previous.head_sha256 === await rangeHash(path,0,previous.head_len);
      const tailMatches = old.archived <= size && (old.archived === 0 || previous.tail_sha256 === await rangeHash(path,Math.max(0,old.archived-4096),Math.min(4096,old.archived)));
      const append = previous.inode === String(info.ino) && previous.dev === String(info.dev) && size > previous.size
        && headMatches && tailMatches && previous.format === format;
      const watermark = append ? old : emptyWatermark();
      const generation = append ? previous.generation : previous.generation+1;
      const chunks = await archiveRange(this.store.directory,this.sourceId,path,watermark.archived,size);
      const headLength = Math.min(size,4096);
      this.store.db.exec('BEGIN IMMEDIATE');
      let added = 0;
      try {
        if (!append) this.markOldSessions(id);
        for (const chunk of chunks) this.store.db.prepare('INSERT INTO archive_chunk VALUES(?,?,?,?,?,?)')
          .run(id,generation,chunk.offset,chunk.byte_len,chunk.sha256,chunk.path);
        const head=await archiveRangeHash(this.store,id,generation,0,headLength);
        const tail=await archiveRangeHash(this.store,id,generation,Math.max(0,size-4096),Math.min(size,4096));
        const zipped=format==='jsonl_zstd';
        const native=Readable.from(archivedBytes(this.store,id,generation,zipped?0:watermark.offset));
        const immutable=zipped?Readable.from(decompressFrames(native)):native;
        for await (const line of linesFromStream(immutable,zipped?0:watermark.offset,zipped?0:watermark.line,32*1024*1024,zipped?watermark.offset:0)) {
          this.record(id,generation,line,watermark,role); added++;
          watermark.offset = line.offset + line.length; watermark.line = line.line;
        }
        native.destroy();
        const after = await stat(path,{bigint:true});
        if (after.ino !== info.ino || after.size < info.size || (after.size === info.size && after.mtimeNs !== info.mtimeNs)) {
          throw new Error('Source was rewritten during ingest');
        }
        watermark.archived = size;
        this.store.db.prepare(`UPDATE source_file SET path=?,role=?,format=?,generation=?,dev=?,inode=?,size=?,mtime_ns=?,
          head_sha256=?,head_len=?,tail_sha256=?,watermark=?,status='active',last_scan_at=? WHERE file_id=?`)
          .run(path,role,format,generation,String(info.dev),String(info.ino),size,String(info.mtimeNs),head,headLength,tail,JSON.stringify(watermark),Date.now(),id);
        this.store.db.exec('COMMIT');
        result.records_added += added; result.files_changed++;
      } catch (error) { this.store.db.exec('ROLLBACK'); throw error; }
    } catch {
      result.files_failed++;
      this.store.db.prepare("UPDATE source_file SET status='error' WHERE file_id=?").run(id);
      this.store.diagnostic(this.sourceId,'file_retry','Source could not be read consistently; cursor retained for retry',id);
    }
  }
  private record(id: string, generation: number, line: Line, state: Watermark, role: string, sourceBody?: Obj): void {
    let body: Obj | null = null;
    let note: string | null = null;
    let disposition: RawRecord['disposition'] = 'unparsed';
    try {
      if (!line.bytes || line.oversized) throw new Error('oversized_line');
      const value = sourceBody ?? JSON.parse(line.bytes.toString('utf8').trim());
      if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('invalid_record_shape');
      body = object(sanitize(value));
      if (role === 'title_index') body = {type:'title_index',payload:body};
      if (!string(body.type)) throw new Error('invalid_record_shape');
      disposition = 'ignored';
    } catch {
      note = line.oversized ? 'oversized_line' : line.bytes?.toString('utf8').trim() === '' ? 'blank_line' : 'invalid_json_or_shape';
      if (note === 'blank_line') disposition = 'ignored';
    }
    const payload = object(body?.payload), type = string(body?.type) ?? 'invalid';
    if (type === 'session_meta' && !string(state.meta.id)) state.meta = payload;
    const ownId = role === 'transcript' ? string(state.meta.id) : indexThreadId(body ?? {});
    const session = ownId ? sessionUid(this.sourceId,ownId) : null;
    if (!session && body) {
      note ??= role==='transcript'?'missing_session_meta':'index_metadata_without_thread';
      if (role==='transcript') disposition='unparsed';
    }
    const eventType = string(payload.type);
    const turn = string(payload.turn_id) ?? string(object(payload.internal_chat_message_metadata_passthrough).turn_id) ?? state.turn;
    if (role === 'transcript' && turn) state.turn = turn;
    const nativeType = [type,eventType,type === 'event_msg' && eventType === 'item_completed' ? string(object(payload.item).type) : null].filter(Boolean).join(':');
    const declaredOrdinal=number(body?.ordinal);
    const ordinal=declaredOrdinal!==null&&Number.isSafeInteger(declaredOrdinal)&&declaredOrdinal>=0?declaredOrdinal:line.line-1;
    if (body?.ordinal!==undefined&&(declaredOrdinal===null||declaredOrdinal!==ordinal)) {note='invalid_ordinal';disposition='unparsed';}
    const recordUid = uid(id,generation,line.line,line.sha256);
    const version = string(state.meta.cli_version) ?? string(payload.cli_version);
    const ts = timestamp(body?.timestamp) ?? timestamp(payload.timestamp) ?? timestamp(payload.updated_at);
    this.store.db.prepare('INSERT INTO raw_record VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run(
      recordUid,id,generation,line.line,ordinal,line.offset,line.length,line.sha256,nativeType,version,ts,session,turn,
      body ? JSON.stringify(body) : null,disposition,null,note);
    if (session) this.store.dirty(session);
    if (note && disposition==='unparsed') this.store.diagnostic(this.sourceId,note,'Raw record retained in L0; see its source position',id,recordUid);
    if (body) {
      const keys = [...Object.keys(body).map(key=>`line.${key}`),...Object.keys(payload).map(key=>`payload.${key}`),...Object.keys(object(payload.item)).map(key=>`item.${key}`)].sort();
      const fingerprint = hash(stableJson(keys));
      const prior = this.store.db.prepare('SELECT fingerprint FROM format_fingerprint WHERE source_id=? AND harness_version=? AND native_type=?').all(this.sourceId,version??'unknown',nativeType);
      if (prior.length && !prior.some(row=>row.fingerprint===fingerprint)) this.store.diagnostic(this.sourceId,'format_drift',`New field shape: ${nativeType}`,id,recordUid);
      this.store.db.prepare('INSERT OR IGNORE INTO format_fingerprint VALUES(?,?,?,?,?,?)')
        .run(this.sourceId,version ?? 'unknown',nativeType,fingerprint,JSON.stringify(keys),Date.now());
    }
    if (eventType && ['task_complete','turn_complete','turn_aborted'].includes(eventType)) state.turn = null;
  }
  private async snapshot(path: string, role: string, records: Obj[], result: IngestResult, original?: Buffer): Promise<string> {
    const id = uid(this.sourceId,role);
    const previous = this.ensureFile(path,id,role,'metadata_jsonl');
    const normalized = records.map(record=>JSON.stringify(record)+'\n');
    const bytes = Buffer.from(normalized.join(''));
    const digest = hash(bytes), trackingDigest = original ? hash(original) : digest;
    result.files_seen++;
    if (previous.head_sha256 === trackingDigest) {
      this.store.db.prepare("UPDATE source_file SET status='active' WHERE file_id=?").run(id); return id;
    }
    // JSON ledgers keep their original bytes in a separate generation manifest. The row export remains directly addressable.
    const generation = previous.generation+1;
    const chunk = await archiveBuffer(this.store.directory,this.sourceId,bytes,0);
    const originalChunk = original ? await archiveBuffer(this.store.directory,this.sourceId,original,0) : null;
    this.store.transaction(() => {
      this.markOldSessions(id);
      this.store.db.prepare('INSERT INTO archive_chunk VALUES(?,?,?,?,?,?)').run(id,generation,0,bytes.length,digest,chunk.path);
      if (originalChunk) this.store.db.prepare('INSERT INTO archive_chunk VALUES(?,?,?,?,?,?)')
        .run(id,-generation,0,original!.length,originalChunk.sha256,originalChunk.path);
      const state = emptyWatermark(); let offset = 0;
      normalized.forEach((text,index) => {
        const lineBytes = Buffer.from(text);
        this.record(id,generation,{bytes:lineBytes,offset,length:lineBytes.length,line:index+1,oversized:false,sha256:hash(lineBytes)},state,role,records[index]);
        offset += lineBytes.length;
      });
      this.store.db.prepare(`UPDATE source_file SET generation=?,size=?,head_sha256=?,status='active',last_scan_at=? WHERE file_id=?`)
        .run(generation,bytes.length,trackingDigest,Date.now(),id);
    });
    result.records_added += records.length; result.files_changed++;
    return id;
  }
}
