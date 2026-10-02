import { createReadStream } from 'node:fs';
import { Readable } from 'node:stream';
import { decompressFrames } from './zstd.ts';
import { createHash } from 'node:crypto';

export interface Line { bytes: Buffer | null; offset: number; length: number; line: number; oversized: boolean; sha256: string; }
/** Offsets are in decompressed bytes for .zst files. Unterminated tails are retried, never committed. */
export async function* lines(path: string, start = 0, firstLine = 0, maxLineBytes = 32 * 1024 * 1024, snapshotSize?: number): AsyncGenerator<Line> {
  const compressed = path.endsWith('.zst');
  if (snapshotSize !== undefined && snapshotSize <= (compressed ? 0 : start)) return;
  const input = createReadStream(path, { start: compressed ? 0 : start, end:snapshotSize === undefined ? undefined : snapshotSize-1, highWaterMark: 256 * 1024 });
  const stream = compressed ? Readable.from(decompressFrames(input)) : input;
  try {yield* linesFromStream(stream,compressed?0:start,compressed?0:firstLine,maxLineBytes,compressed?start:0);}
  finally {stream.destroy();input.destroy();}
}
export async function* linesFromStream(stream:Readable,initialOffset=0,firstLine=0,maxLineBytes=32*1024*1024,skipBefore=0):AsyncGenerator<Line>{
  let offset=initialOffset,line=firstLine;
  let parts: Buffer[] = [];
  let size = 0;
  let oversized = false;
  let digest = createHash('sha256');
  try {
    for await (const chunk of stream) {
      const buffer = chunk as Buffer;
      let cursor = 0;
      while (cursor < buffer.length) {
        const newline = buffer.indexOf(10,cursor);
        const end = newline === -1 ? buffer.length : newline + 1;
        const part = buffer.subarray(cursor,end);
        size += part.length;
        digest.update(part);
        if (size > maxLineBytes) { oversized = true; parts = []; }
        if (!oversized) parts.push(part);
        if (newline !== -1) {
          line++;
          const record = { bytes: oversized ? null : Buffer.concat(parts,size), offset, length: size, line, oversized, sha256:digest.digest('hex') };
          if (offset >= skipBefore) yield record;
          offset += size;
          parts = []; size = 0; oversized = false;
          digest = createHash('sha256');
        }
        cursor = end;
      }
    }
  } finally { stream.destroy(); }
}
