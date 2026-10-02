import { createReadStream } from 'node:fs';
import { mkdir, writeFile, rename, readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { zstdCompressSync, zstdDecompressSync } from 'node:zlib';
import { Readable } from 'node:stream';
import { hash } from './util.ts';
import { decompressFrames } from './zstd.ts';
import type { ConnectorStore } from './store.ts';
import { sanitize } from './privacy.ts';
import type { Json } from './types.ts';

export interface ArchiveChunk { offset: number; byte_len: number; sha256: string; path: string; }
export async function archiveBuffer(directory: string, source: string, bytes: Buffer, offset: number): Promise<ArchiveChunk> {
  const digest = hash(bytes);
  const dir = join(directory,'raw',source);
  await mkdir(dir,{recursive:true,mode:0o700});
  const path = join(dir,`${digest}.zst`);
  try { await stat(path); }
  catch {
    const temporary = `${path}.${randomUUID()}.tmp`;
    await writeFile(temporary,zstdCompressSync(bytes),{mode:0o600,flag:'wx'});
    await rename(temporary,path);
  }
  return { offset, byte_len: bytes.length, sha256:digest, path };
}
/** Each immutable chunk is published before its SQLite manifest commits; a crash can only leave an unused chunk. */
export async function archiveRange(directory: string, source: string, path: string, start: number, end: number): Promise<ArchiveChunk[]> {
  const chunks: ArchiveChunk[] = [];
  if (end <= start) return chunks;
  let offset = start;
  for await (const value of createReadStream(path,{start,end:end-1,highWaterMark:1024*1024})) {
    const bytes = value as Buffer;
    chunks.push(await archiveBuffer(directory,source,bytes,offset)); offset += bytes.length;
  }
  if (offset !== end) throw new Error('Source changed while archiving');
  return chunks;
}
export async function* archivedBytes(store: ConnectorStore, fileId: string, generation: number): AsyncGenerator<Buffer> {
  const chunks = store.db.prepare('SELECT * FROM archive_chunk WHERE file_id=? AND generation=? ORDER BY offset')
    .all(fileId,generation) as unknown as ArchiveChunk[];
  let offset = 0;
  for (const chunk of chunks) {
    if (chunk.offset !== offset) throw new Error('Archive has a gap');
    const bytes = zstdDecompressSync(await readFile(chunk.path));
    if (hash(bytes) !== chunk.sha256 || bytes.length !== chunk.byte_len) throw new Error('Archive checksum mismatch');
    yield bytes; offset += bytes.length;
  }
}
export async function readRawRecord(store: ConnectorStore, recordUid: string): Promise<Buffer> {
  const record = store.db.prepare(`SELECT r.*, f.format FROM raw_record r JOIN source_file f USING(file_id) WHERE record_uid=?`).get(recordUid);
  if (!record) throw new Error('Unknown raw record');
  const chunks=archivedBytes(store,String(record.file_id),Number(record.generation));
  const first=await chunks.next();
  const magic=!first.done&&first.value.length>=4?first.value.readUInt32LE():null;
  const compressed=magic===0xfd2fb528||(magic!==null&&magic>=0x184d2a50&&magic<=0x184d2a5f);
  const native = Readable.from((async function*(){if(!first.done)yield first.value;yield* chunks;})());
  // The logical file's current format can differ from this immutable generation.
  const stream = compressed ? Readable.from(decompressFrames(native)) : native;
  const start = Number(record.byte_offset), end = start + Number(record.byte_len);
  let cursor = 0;
  const parts: Buffer[] = [];
  try {
    for await (const value of stream) {
      const bytes = value as Buffer;
      if (cursor < end && cursor + bytes.length > start) parts.push(bytes.subarray(Math.max(0,start-cursor),Math.min(bytes.length,end-cursor)));
      cursor += bytes.length;
      if (cursor >= end) break;
    }
  } finally { stream.destroy(); native.destroy(); }
  const bytes = Buffer.concat(parts);
  if (bytes.length !== Number(record.byte_len)) throw new Error('Incomplete archive record');
  return bytes;
}
/** Analysis drill-down keeps projection redaction while lifting the 8 KB tool preview budget. */
export async function readRedactedRecord(store:ConnectorStore,recordUid:string):Promise<Json> {
  const bytes=await readRawRecord(store,recordUid);
  return sanitize(JSON.parse(bytes.toString('utf8')), '',32*1024*1024,32*1024*1024);
}
