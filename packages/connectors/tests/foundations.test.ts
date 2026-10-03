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
import { commandHead } from '../src/shell.ts';

test('streaming JSONL retries an incomplete tail and handles concatenated zstd frames', async () => {
  const dir = await mkdtemp(join(tmpdir(),'orbit-lines-'));
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
  const dir = await mkdtemp(join(tmpdir(),'orbit-db-'));
  try {
    let store = new ConnectorStore(dir);
    assert.equal(store.db.prepare('PRAGMA user_version').get()?.user_version,3);
    store.close(); store = new ConnectorStore(dir); store.close();
    assert.equal((await stat(join(dir,'orbit.db'))).mode & 0o777,0o600);
    assert.throws(() => validateEvent({event_uid:'e',session_uid:'s',seq:1,ts:1,kind:'message.user',actor:'human',
      turn_uid:null,parent_uid:null,call_id:null,text:'hi',text_truncated:0,attrs:{origin:'invented'},ext:{native_type:'event_msg:user_message'},record_uid:'r',native_id:null,
      native_key:['s','r'],event_path:'message.text',contract_version:1,mapper_version:'test'}));
  } finally { await rm(dir,{recursive:true,force:true}); }
});
test('Basic authentication, cookie headers and credentialed URI schemes are redacted',()=>{
  const text='Authorization: Basic dXNlcjpwYXNzd29yZA==\nCookie: sid=opaque-session-value\nSet-Cookie: auth=opaque-cookie-value; HttpOnly\npostgres://alice:opaque-db-password@db.example/test';
  const result=JSON.stringify(sanitize({text,cookie:'opaque-structured-cookie',setCookie:'opaque-set-cookie'}));
  for(const secret of ['dXNlcjpwYXNzd29yZA==','opaque-session-value','opaque-cookie-value','opaque-db-password','opaque-structured-cookie','opaque-set-cookie'])assert.ok(!result.includes(secret));
  assert.ok(result.includes('db.example/test'));
});
test('all authorization schemes and raw image-generation media stay out of sanitized projections',()=>{
  const rawImage='iVBORw0KGgoAAAANSUhEUgAAfixtureBase64Image';
  const result=JSON.stringify(sanitize({image:{type:'image_generation_call',result:rawImage},
    text:'Authorization: Digest response="opaque-digest"\nProxy-Authorization: Negotiate opaque-negotiate\nAuthorization: AWS4-HMAC-SHA256 Signature=opaque-signature'}));
  for(const secret of [rawImage,'opaque-digest','opaque-negotiate','opaque-signature'])assert.ok(!result.includes(secret));
  assert.ok(result.includes('attachment:sha256:'));
});
test('command heads name the effective program, never a path, assignment or whole script',()=>{
  const cases:[unknown,string|null][]=[
    [['/bin/zsh','-lc','cd x && rg foo'],'rg'],
    [['/bin/zsh','-lc','set -e\nuv run python scripts/check.py\npnpm test'],'uv run'],
    [['bash','-c','S=/tmp/x; ls $S'],'ls'],
    ['cd /repo && git -C sub status --short','git status'],
    ['/usr/local/bin/pnpm --dir packages/connectors check','pnpm check'],
    ['npx tsc --noEmit','npx tsc'],
    ['timeout 30 env FOO=1 pytest -q tests','pytest'],
    ['tail -n 5 .local/main-integration-progress.log','tail'],
    ['echo "unterminated','echo'],
    [['pnpm','test'],'pnpm test'],
    ['for f in *.py; do black "$f"; done','black'],
    ['$HOME/bin/tool',null],[[],null],[42,null],
  ];
  for (const [command,expected] of cases) assert.equal(commandHead(command),expected,JSON.stringify(command));
});
test('vendor token formats are redacted while counters, token types and look-alike identifiers survive',()=>{
  const fill=(n:number,c='A')=>c.repeat(n);
  const secrets:[string,string][]=[
    ['xoxb-'+'123456789012-'+fill(24,'a'),'<redacted:token>'],['xoxp-'+fill(30,'9'),'<redacted:token>'],
    ['AIza'+fill(35,'B'),'<redacted:api_key>'],['sk_live_'+fill(24,'c'),'<redacted:api_key>'],['sk_test_'+fill(24,'d'),'<redacted:api_key>'],
    ['eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.'+fill(43,'e'),'<redacted:jwt>'],
    ['npm_'+fill(36,'f'),'<redacted:api_key>'],['glpat-'+fill(20,'g'),'<redacted:api_key>'],['hf_'+fill(34,'h'),'<redacted:api_key>'],
    ['ya29.'+fill(40,'i'),'<redacted:token>'],
  ];
  for (const [secret,label] of secrets) {
    const clean=String(sanitize(`value ${secret} end`));
    assert.ok(!clean.includes(secret),secret);assert.equal(clean,`value ${label} end`);
  }
  const keep={max_tokens:4096,token_type:'bearer',input_tokens:12,output_tokens:3,text:'max_tokens=4096 token_type: bearer input_tokens: 12',
    words:'hf_hub_download npm_config_cache sk_test glpat- eyJhbGci AIzaShort self_hf_'+fill(34,'h')};
  assert.deepEqual(sanitize(keep),keep);
});
test('truncation cuts on a UTF-8 character boundary',()=>{
  for (const budget of [8190,8191,8192]) {
    const value=String(sanitize('中'.repeat(5000),'output',32*1024*1024,budget));
    assert.ok(!value.includes('\uFFFD'));assert.match(value,/<truncated:sha256:[0-9a-f]{64}>$/);
    const kept=value.replace(/<truncated:.*$/,'');assert.ok(Buffer.byteLength(kept)<=budget&&Buffer.byteLength(kept)>budget-3);
  }
});
test('full-text rows follow event rowids, so deleting an event removes exactly its FTS row',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'orbit-fts-'));
  const store=new ConnectorStore(dir);
  try {
    store.db.exec("INSERT INTO source VALUES('s','codex','/r','r',1,1); INSERT INTO source_file(file_id,source_id,path,role,format) VALUES('f','s','/r/x','transcript','jsonl');"+
      "INSERT INTO raw_record VALUES('r','f',1,1,0,0,1,'h','t',null,null,'sess',null,null,'mapped',null,null); INSERT INTO session(session_uid,source_id,native_id,kind) VALUES('sess','s','n','main');");
    for (const [id,text] of [['e1','alpha words'],['e2','beta words']] as const) store.db.prepare(`INSERT INTO event(event_uid,session_uid,seq,ts,kind,actor,text,attrs,record_uid,native_key,event_path,mapper_version)
      VALUES(?,'sess',?,null,'message.user','human',?,'{"time":{"quality":"missing"}}','r','[]','p','m')`).run(id,id==='e1'?0:1,text);
    assert.deepEqual(store.db.prepare("SELECT event_uid FROM event_fts WHERE event_fts MATCH 'words' ORDER BY event_uid").all().map(row=>row.event_uid),['e1','e2']);
    store.db.prepare("DELETE FROM event WHERE event_uid='e1'").run();
    assert.deepEqual(store.db.prepare("SELECT event_uid FROM event_fts WHERE event_fts MATCH 'words'").all().map(row=>row.event_uid),['e2']);
  } finally { store.close(); await rm(dir,{recursive:true,force:true}); }
});
