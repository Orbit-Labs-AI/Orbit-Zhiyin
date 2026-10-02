import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, appendFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { zstdCompressSync } from 'node:zlib';
import { lines } from '../src/lines.ts';
import { sanitize } from '../src/privacy.ts';
import { ConnectorStore } from '../src/store.ts';
import { validateEvent } from '../src/contract.ts';

test('streaming JSONL retries an incomplete tail and handles concatenated zstd frames', async () => {
  const dir = await mkdtemp(join(tmpdir(),'tandem-lines-'));
  try {
    const file = join(dir,'rollout.jsonl');
    await writeFile(file,'{"a":1}\n{"b":');
    const first = await Array.fromAsync(lines(file));
    assert.equal(first.length,1);
    assert.equal(first[0]?.length,8);
    await appendFile(file,'2}\n');
    const next = await Array.fromAsync(lines(file,8,1));
    assert.equal(next[0]?.bytes?.toString(),'{"b":2}\n');
    assert.equal(next[0]?.line,2);
    await writeFile(file+'.zst',Buffer.concat([zstdCompressSync('{"a":1}\n'),zstdCompressSync('{"b":2}\n')]));
    assert.equal((await Array.fromAsync(lines(file+'.zst'))).length,2);
    assert.equal((await Array.fromAsync(lines(file+'.zst',8,1))).length,1);
    await writeFile(file,'too-large\nsmall\n');
    const limited = await Array.fromAsync(lines(file,0,0,7));
    assert.equal(limited[0]?.oversized,true);
    assert.equal(limited[1]?.bytes?.toString(),'small\n');
  } finally { await rm(dir,{recursive:true,force:true}); }
});
test('sanitized copies omit identities and redact nested secrets and media', () => {
  const secret = 'sk-'+'x'.repeat(32);
  const output = JSON.stringify(sanitize({ creator_user_id:'private-person', nest:{ api_key:secret },
    text:`hello ${secret}`, image_url:'data:image/png;base64,YWJj', encrypted_content:'opaque-data' }));
  assert.ok(!output.includes(secret)); assert.ok(!output.includes('private-person'));
  assert.ok(output.includes('attachment:sha256:')); assert.ok(output.includes('opaque:sha256:'));
});
test('credential variants are redacted without replacing native usage counters or identity keys',()=>{
  const value=sanitize({token:'opaque-token-value',client_secret:'opaque-client-value',secret_access_key:'opaque-secret-value',
    clientSecret:'opaque-camel-value',AWS_SECRET_ACCESS_KEY:'opaque-aws-value',nested:{refreshToken:'opaque-refresh-value'},
    input_tokens:10,last_token_usage:{input_tokens:20},request_key:['source','identity'],snapshot_key:'snapshot-identity'});
  const serialized=JSON.stringify(value);
  assert.ok(!serialized.includes('opaque-'));
  assert.ok(serialized.includes('"input_tokens":10'));assert.ok(serialized.includes('"last_token_usage":{"input_tokens":20}'));
  assert.ok(serialized.includes('snapshot-identity'));
  const wrapped=JSON.stringify(sanitize({arguments:JSON.stringify({token:'opaque-nested-token',clientSecret:'opaque-nested-secret',input_tokens:12})}));
  assert.ok(!wrapped.includes('opaque-nested'));assert.ok(wrapped.includes('input_tokens'));
  const opaque=sanitize({encrypted_content:'ciphertext',output:'z'.repeat(20000)});
  assert.deepEqual(sanitize(opaque),opaque);
});
test('SQLite migration is repeatable, private and rejects invalid event attributes', async () => {
  const dir = await mkdtemp(join(tmpdir(),'tandem-db-'));
  try {
    let store = new ConnectorStore(dir);
    assert.equal(store.db.prepare('PRAGMA user_version').get()?.user_version,2);
    store.close(); store = new ConnectorStore(dir); store.close();
    assert.equal((await stat(join(dir,'tandem.db'))).mode & 0o777,0o600);
    assert.throws(() => validateEvent({event_uid:'e',session_uid:'s',seq:1,ts:1,kind:'message.user',actor:'human',
      turn_uid:null,parent_uid:null,call_id:null,text:'hi',text_truncated:0,attrs:{origin:'invented'},ext:{},record_uid:'r',native_id:null,
      native_key:['s','r'],event_path:'message.text',contract_version:1,mapper_version:'test'}));
  } finally { await rm(dir,{recursive:true,force:true}); }
});
