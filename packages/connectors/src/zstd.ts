import { Readable } from 'node:stream';
import { createZstdDecompress, constants } from 'node:zlib';

/** Frame boundaries from RFC 8878 §3.1; Node 24/26 releases may stop at the first frame. */
export async function* decompressFrames(input: Readable): AsyncGenerator<Buffer> {
  const iterator = input[Symbol.asyncIterator]();
  let buffer: Buffer = Buffer.alloc(0);
  let cursor = 0;
  async function* take(length: number): AsyncGenerator<Buffer> {
    while (length > 0) {
      if (cursor === buffer.length) {
        const next = await iterator.next();
        if (next.done) throw new Error('Incomplete zstd frame; retry after the writer finishes');
        buffer = next.value as Buffer; cursor = 0;
      }
      const size = Math.min(length,buffer.length-cursor);
      yield buffer.subarray(cursor,cursor+size); cursor += size; length -= size;
    }
  }
  async function fixed(length: number): Promise<Buffer> { return Buffer.concat(await Array.fromAsync(take(length)),length); }
  try {
    while (true) {
      if (cursor === buffer.length) {
        const next = await iterator.next();
        if (next.done) break;
        buffer = next.value as Buffer; cursor = 0;
      }
      const magicBytes = await fixed(4);
      const magic = magicBytes.readUInt32LE();
      if (magic >= 0x184d2a50 && magic <= 0x184d2a5f) {
        const size = (await fixed(4)).readUInt32LE();
        for await (const ignored of take(size)) void ignored;
        continue;
      }
      if (magic !== 0xfd2fb528) throw new Error('Invalid zstd frame magic');
      const descriptor = await fixed(1);
      const flag = descriptor[0]!;
      if (flag & 0x08) throw new Error('Reserved zstd frame flag');
      const single = Boolean(flag & 0x20), checksum = Boolean(flag & 0x04);
      const contentSize = [single ? 1 : 0,2,4,8][flag >> 6]!;
      const dictSize = [0,1,2,4][flag & 3]!;
      const header = Buffer.concat([magicBytes,descriptor,await fixed((single ? 0 : 1)+contentSize+dictSize)]);
      async function* frame(): AsyncGenerator<Buffer> {
        yield header;
        let last = false;
        while (!last) {
          const bytes = await fixed(3);
          const block = bytes.readUIntLE(0,3), type = (block >> 1) & 3;
          if (type === 3) throw new Error('Reserved zstd block type');
          last = Boolean(block & 1);
          yield bytes;
          yield* take(type === 1 ? 1 : block >> 3);
        }
        if (checksum) yield await fixed(4);
      }
      const compressed = Readable.from(frame());
      const decoded = compressed.pipe(createZstdDecompress({params:{[constants.ZSTD_d_windowLogMax]:27}}));
      compressed.on('error',error => decoded.destroy(error));
      try { for await (const bytes of decoded) yield bytes as Buffer; }
      finally { decoded.destroy(); compressed.destroy(); }
    }
  } finally { input.destroy(); }
}
