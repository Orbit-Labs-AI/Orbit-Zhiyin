import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, appendFile, rename, rm, stat, realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { DatabaseSync } from 'node:sqlite';
import { zstdCompressSync } from 'node:zlib';
import { CodexConnector } from '../src/ingest.ts';
import { ConnectorStore } from '../src/store.ts';
import { readRawRecord, readRedactedRecord, archivedBytes } from '../src/archive.ts';
import { discoverCodex } from '../src/discovery.ts';
import { sessionUid } from '../src/util.ts';
import { hash,uid } from '../src/util.ts';
import { sanitize } from '../src/privacy.ts';
import { readFileSync } from 'node:fs';
import { watchCodex } from '../src/watch.ts';
import { promisify } from 'node:util';
import { execFile,spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';

type Sandbox = {root:string, home:string, file:string, store:ConnectorStore, connector:CodexConnector};
async function sandbox(action:(s:Sandbox)=>Promise<void>):Promise<void> {
  const root=await realpath(await mkdtemp(join(tmpdir(),'tandem-connector-'))),home=join(root,'codex');
  await mkdir(join(home,'sessions','2026','10','01'),{recursive:true});
  await mkdir(join(home,'archived_sessions'));
  const store=new ConnectorStore(join(root,'tandem')),connector=new CodexConnector(store,home);
  try { await action({root,home,file:join(home,'sessions','2026','10','01','rollout-main.jsonl'),store,connector}); }
  finally { store.close(); await rm(root,{recursive:true,force:true}); }
}
async function fixture(name='paginated'):Promise<string> { return readFile(new URL(`./fixtures/${name}.jsonl`,import.meta.url),'utf8'); }
const scalar=(s:Sandbox,query:string):number=>Number(s.store.db.prepare(query).get()?.n);
const jsonLine=(type:string,payload:unknown,ordinal=0)=>JSON.stringify({type,payload,ordinal,timestamp:new Date(Date.UTC(2026,9,2,0,0,ordinal)).toISOString()})+'\n';

test('paginated records are fully accounted; mirrors do not duplicate messages, tools or tokens',async()=>sandbox(async s=>{
  const native=await fixture(); await writeFile(s.file,native);
  const first=await s.connector.ingest();
  assert.equal(first.records_added,native.trim().split('\n').length);
  assert.equal(Object.values(first.accounting).reduce((a,b)=>a+b,0),first.records_added);
  assert.equal(first.accounting.unparsed??0,0);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE kind='message.user' AND json_extract(attrs,'$.origin')='human'"),1);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE kind='message.assistant'"),2);
  assert.equal(scalar(s,'SELECT count(*) n FROM model_call'),1);
  assert.deepEqual(s.store.db.prepare('SELECT input_tokens,cache_read_tokens,cache_write_tokens,output_tokens,reasoning_tokens,cost_usd,cost_source,model_raw FROM model_call').get(),
    Object.assign(Object.create(null),{input_tokens:50,cache_read_tokens:40,cache_write_tokens:10,output_tokens:20,reasoning_tokens:5,cost_usd:null,cost_source:'unknown',model_raw:'gpt-fixture'}));
  assert.equal(scalar(s,'SELECT count(*) n FROM tool_call WHERE is_wrapper=0'),2);
  assert.equal(scalar(s,"SELECT count(*) n FROM tool_call WHERE status='failed' AND exit_code=2"),1);
  const late=s.store.db.prepare("SELECT attrs FROM event WHERE kind='tool.call' AND call_id='exec-late'").get();
  assert.equal(JSON.parse(String(late?.attrs)).parent_wrapper_id,'wrapper1');
  assert.equal(JSON.parse(String(late?.attrs)).cwd,'/sample/repo');
  const windows=JSON.parse(String(s.store.db.prepare("SELECT attrs FROM event WHERE kind='ui.state'").get()?.attrs)).windows;
  assert.deepEqual(windows.map((window:{window_kind:string})=>window.window_kind),['weekly','five_hour']);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE kind='context.compaction'"),1);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE kind='unknown'"),1);
  assert.equal(scalar(s,"SELECT count(*) n FROM diagnostic WHERE code='unknown_type'"),1);
  const originalEvents=s.store.db.prepare('SELECT * FROM event ORDER BY event_uid').all();
  const second=await s.connector.ingest();
  assert.equal(second.records_added,0); assert.equal(second.sessions_rebuilt,0);
  assert.deepEqual(s.store.db.prepare('SELECT * FROM event ORDER BY event_uid').all(),originalEvents);
  assert.ok(!JSON.stringify(s.store.db.prepare('SELECT body FROM raw_record').all()).includes('test-private-person'));
  const firstRecord=s.store.db.prepare("SELECT record_uid FROM current_record WHERE native_type='session_meta'").get();
  assert.equal((await readRawRecord(s.store,String(firstRecord?.record_uid))).toString(),native.split('\n')[0]+'\n');
}));
test('legacy aliases use UI messages, skip unchanged cumulative usage and synthetic window saturation',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture('legacy')); const result=await s.connector.ingest();
  assert.equal(result.accounting.unparsed??0,0);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE kind='message.user'"),1);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE kind='message.assistant'"),1);
  assert.equal(scalar(s,'SELECT count(*) n FROM model_call'),1);
  assert.equal(s.store.db.prepare('SELECT status FROM turn').get()?.status,'interrupted');
  assert.equal(s.store.db.prepare('SELECT status FROM tool_call').get()?.status,'unknown');
  assert.equal(scalar(s,"SELECT count(*) n FROM current_record WHERE disposition='duplicate' AND ref_event_uid IS NOT NULL"),3);
}));
test('incremental JSONL preserves raw pending bytes and retries the incomplete final line',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture()); await s.connector.ingest();
  const complete=jsonLine('event_msg',{type:'task_started',turn_id:'t2'},30);
  await appendFile(s.file,complete.slice(0,-2));
  assert.equal((await s.connector.ingest()).records_added,0);
  await appendFile(s.file,complete.slice(-2));
  assert.equal((await s.connector.ingest()).records_added,1);
  const file=s.store.db.prepare("SELECT * FROM source_file WHERE role='transcript'").get()!;
  const archived=Buffer.concat(await Array.fromAsync(archivedBytes(s.store,String(file.file_id),Number(file.generation))));
  assert.deepEqual(archived,await readFile(s.file));
  assert.equal(scalar(s,'SELECT count(*) n FROM turn'),2);
}));
test('rewrites replace the current projection while retaining previous raw generations; deletion keeps evidence',async()=>sandbox(async s=>{
  const original=await fixture(); await writeFile(s.file,original); await s.connector.ingest();
  const record=s.store.db.prepare("SELECT record_uid FROM current_record WHERE native_type='event_msg:item_completed:UserMessage'").get()!;
  await writeFile(s.file,original.replaceAll('请修复样例','请检查样例'));
  assert.ok((await s.connector.ingest()).records_added>0);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE text='请修复样例'"),0);
  assert.ok((await readRawRecord(s.store,String(record.record_uid))).toString().includes('请修复样例'));
  const count=scalar(s,'SELECT count(*) n FROM event');
  await rm(s.file); await s.connector.ingest();
  assert.equal(s.store.db.prepare("SELECT status FROM source_file WHERE role='transcript'").get()?.status,'gone_upstream');
  assert.equal(scalar(s,'SELECT count(*) n FROM event'),count);
}));
test('archival moves and .zst replacement preserve one logical file, with streaming concatenated-frame decoding',async()=>sandbox(async s=>{
  const original=await fixture(); await writeFile(s.file,original); await s.connector.ingest();
  const count=scalar(s,'SELECT count(*) n FROM event'),fileId=s.store.db.prepare("SELECT file_id FROM source_file WHERE role='transcript'").get()?.file_id;
  const oldRecord=s.store.db.prepare("SELECT record_uid FROM current_record WHERE native_type='session_meta'").get()!;
  const archived=join(s.home,'archived_sessions','rollout-main.jsonl'); await rename(s.file,archived);
  assert.equal((await s.connector.ingest()).records_added,0);
  const split=original.indexOf('\n',original.indexOf('\n')+1)+1;
  await writeFile(archived+'.zst',Buffer.concat([zstdCompressSync(original.slice(0,split)),zstdCompressSync(original.slice(split))]));
  await rm(archived); const result=await s.connector.ingest();
  assert.equal(result.files_changed,1);
  assert.equal(scalar(s,'SELECT count(*) n FROM event'),count);
  assert.equal(s.store.db.prepare("SELECT file_id FROM source_file WHERE role='transcript'").get()?.file_id,fileId);
  const record=s.store.db.prepare("SELECT record_uid FROM current_record WHERE native_type='session_meta'").get()!;
  assert.equal((await readRawRecord(s.store,String(record.record_uid))).toString(),original.split('\n')[0]+'\n');
  assert.equal((await readRawRecord(s.store,String(oldRecord.record_uid))).toString(),original.split('\n')[0]+'\n');
}));
test('thread_spawn inherited prefix is excluded; guardian records remain independent of that cutoff',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());
  const child=[
    jsonLine('session_meta',{id:'child',session_id:'main',parent_thread_id:'main',thread_source:'subagent',source:{subagent:{thread_spawn:{parent_thread_id:'main',depth:1}}},subagent_history_start_ordinal:4},0),
    jsonLine('session_meta',{id:'main',session_id:'main'},1),
    jsonLine('event_msg',{type:'task_started',turn_id:'t1'},2),
    jsonLine('event_msg',{type:'item_completed',turn_id:'t1',item:{type:'UserMessage',id:'u1',content:[{type:'text',text:'请修复样例'}]}},3),
    jsonLine('event_msg',{type:'task_started',turn_id:'child-turn'},4),
    jsonLine('turn_context',{turn_id:'child-turn',model:'gpt-fixture'},5),
    jsonLine('token_usage_record',{turn_id:'child-turn',response_id:'child-response',usage:{input_tokens:10,output_tokens:5}},6)
  ].join('');
  await writeFile(join(s.home,'sessions','rollout-child.jsonl'),child);
  const guardian=[jsonLine('session_meta',{id:'guardian',session_id:'main',parent_thread_id:'main',thread_source:'guardian_review',source:{subagent:{other:'guardian'}},subagent_history_start_ordinal:5},0),
    jsonLine('event_msg',{type:'task_started',turn_id:'guard-turn'},1),jsonLine('turn_context',{turn_id:'guard-turn',model:'codex-auto-review'},2),
    jsonLine('token_usage_record',{turn_id:'guard-turn',response_id:'guard-response',usage:{input_tokens:1000,output_tokens:500}},3),
    jsonLine('event_msg',{type:'task_complete',turn_id:'guard-turn'},4)].join('');
  await writeFile(join(s.home,'archived_sessions','rollout-guardian.jsonl'),guardian); await s.connector.ingest();
  const childUid=sessionUid(s.connector.sourceId,'child'),guardianUid=sessionUid(s.connector.sourceId,'guardian');
  assert.equal(s.store.db.prepare('SELECT count(*) n FROM current_record WHERE session_uid=? AND disposition=\'replayed\'').get(childUid)?.n,3);
  assert.equal(s.store.db.prepare('SELECT count(*) n FROM turn WHERE session_uid=?').get(childUid)?.n,1);
  assert.equal(s.store.db.prepare('SELECT count(*) n FROM model_call WHERE session_uid=?').get(guardianUid)?.n,1);
  assert.equal(scalar(s,'SELECT count(*) n FROM main_model_usage'),2);
}));
test('read-only state index sets title priority, project metadata, imports and spawn edges without reading identity columns',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());
  const indexPath=join(s.home,'state_5.sqlite');
  const db=new DatabaseSync(indexPath);
  db.exec(`PRAGMA journal_mode=WAL; CREATE TABLE threads(id TEXT, rollout_path TEXT, name TEXT, title TEXT, cwd TEXT, model TEXT, creator_account_id TEXT);
    CREATE TABLE thread_spawn_edges(parent_thread_id TEXT,child_thread_id TEXT,status TEXT);`);
  db.prepare('INSERT INTO threads VALUES(?,?,?,?,?,?,?)').run('main',s.file,'手动名称','首条标题','/sample/repo','gpt-fixture','never-read-account');
  await writeFile(join(s.home,'session_index.jsonl'),JSON.stringify({id:'main',thread_name:'缓存名称',updated_at:'2026-10-02T00:00:00Z'})+'\n');
  await writeFile(join(s.home,'external_agent_session_imports.json'),JSON.stringify({records:[{imported_thread_id:'main',source_path:'/sample/claude.jsonl',content_sha256:'fixture-sha',imported_at:1}]}));
  const before=await readFile(indexPath); const result=await s.connector.ingest();
  assert.equal(result.accounting.unparsed??0,0);
  assert.equal(s.store.db.prepare('SELECT title FROM session').get()?.title,'手动名称');
  assert.equal(s.store.db.prepare('SELECT kind FROM session').get()?.kind,'import');
  assert.equal(scalar(s,'SELECT count(*) n FROM main_model_usage'),0);
  assert.deepEqual(await readFile(indexPath),before);
  assert.ok(!JSON.stringify(s.store.db.prepare('SELECT body FROM raw_record').all()).includes('never-read-account'));
  db.prepare('UPDATE threads SET name=?').run('新名称'); await s.connector.ingest();
  assert.equal(s.store.db.prepare('SELECT title FROM session').get()?.title,'新名称');
  db.close();
}));
test('a stale maintenance file does not block ingestion; malformed records and drift remain explicit and bounded',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture()); await mkdir(join(s.home,'.tmp'));
  const lock=join(s.home,'.tmp','rollout-maintenance.lock'); await writeFile(lock,'');
  assert.equal((await s.connector.ingest()).maintenance_skipped,false);
  assert.ok(scalar(s,'SELECT count(*) n FROM raw_record')>0); await rm(lock);
  await appendFile(s.file,'not-json\n'+jsonLine('world_state',{full:false,state:{},new_field:'preserve'},31));
  const result=await s.connector.ingest();
  assert.equal(result.accounting.unparsed,1);
  assert.ok(scalar(s,"SELECT count(*) n FROM diagnostic WHERE code='format_drift'")>0);
  assert.equal(Object.values(result.accounting).reduce((a,b)=>a+b,0),scalar(s,'SELECT count(*) n FROM current_record'));
  assert.equal((await stat(join(s.root,'tandem','raw'))).mode&0o777,0o700);
}));
test('an actually held maintenance lock defers ingest without acquiring a lock in the connector',async t=>sandbox(async s=>{
  await writeFile(s.file,await fixture());await mkdir(join(s.home,'.tmp'));
  const lock=join(s.home,'.tmp','rollout-maintenance.lock');await writeFile(lock,'');
  const holder=spawn('python3',['-c','import sys,fcntl; f=open(sys.argv[1],"rb"); fcntl.flock(f,fcntl.LOCK_EX); print("held",flush=True); sys.stdin.read()',lock]);
  try {
    await once(holder.stdout,'data');
    const discovery=await discoverCodex(s.home);
    if(discovery.maintenance_state==='unknown'){t.skip('OS lock observer unavailable');return;}
    assert.equal(discovery.maintenance,true);
    assert.equal((await s.connector.ingest()).maintenance_skipped,true);
    assert.equal(scalar(s,'SELECT count(*) n FROM raw_record'),0);
  } finally {holder.stdin.end();await once(holder,'exit');}
}));
test('unknown sources are discovered without reading credentials or following directory symlinks',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture()); await writeFile(join(s.home,'auth.json'),'do not read');
  const discovery=await discoverCodex(s.home);
  assert.deepEqual(discovery.files,[s.file]);
  assert.throws(()=>new CodexConnector(s.store,s.root),/outside CODEX_HOME/);
}));

test('distinct identical UI messages stay distinct; usage follows model switches within the same turn',async()=>sandbox(async s=>{
  const text=await fixture();
  const beforeEnd=text.trim().split('\n').slice(0,-1).join('\n')+'\n';
  await writeFile(s.file,beforeEnd+
    jsonLine('event_msg',{type:'item_completed',turn_id:'t1',item:{type:'UserMessage',id:'u2',content:[{type:'text',text:'请修复样例'}]}},30)+
    jsonLine('event_msg',{type:'thread_settings_applied',thread_settings:{model:'gpt-second',reasoning_effort:'ultra'}},31)+
    jsonLine('token_usage_record',{turn_id:'t1',response_id:'second-response',usage:{input_tokens:20,output_tokens:10}},32));
  await s.connector.ingest();
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE kind='message.user' AND actor='human'"),2);
  assert.deepEqual(s.store.db.prepare('SELECT model_raw,effort_raw FROM model_call ORDER BY ts').all().map(row=>[row.model_raw,row.effort_raw]),[['gpt-fixture','high'],['gpt-second','ultra']]);
}));
test('MCP error flags and declined commands are authoritative, with exact originals retained after truncation and redaction',async()=>sandbox(async s=>{
  const secret='sk-'+'x'.repeat(32),long='z'.repeat(20000);
  await writeFile(s.file,await fixture()+
    jsonLine('event_msg',{type:'item_completed',turn_id:'t2',item:{type:'McpToolCall',id:'m1',server:'fixture',tool:'search',arguments:{api_key:secret},status:'completed',result:{isError:true,content:[{type:'text',text:long+secret}]}}},31)+
    jsonLine('event_msg',{type:'item_completed',turn_id:'t2',item:{type:'CommandExecution',id:'denied1',command:['pwd'],cwd:'file:///sample/repo',status:'declined',exit_code:-1}},32));
  const result=await s.connector.ingest(); assert.equal(result.accounting.unparsed??0,0);
  assert.equal(scalar(s,"SELECT count(*) n FROM tool_call WHERE name_raw='mcp__fixture__search' AND status='failed'"),1);
  assert.equal(scalar(s,"SELECT count(*) n FROM tool_call WHERE approval='denied'"),1);
  const event=s.store.db.prepare("SELECT * FROM event WHERE kind='tool.result' AND call_id='m1'").get()!;
  assert.equal(event.text_truncated,1); assert.ok(!JSON.stringify(event).includes(secret));
  assert.ok((await readRawRecord(s.store,String(event.record_uid))).toString().includes(secret));
  const full=JSON.stringify(await readRedactedRecord(s.store,String(event.record_uid)));
  assert.ok(full.length>8192);assert.ok(!full.includes(secret));
}));
test('Codex project metadata is accounted without creating project IDs as fake sessions',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());
  const db=new DatabaseSync(join(s.home,'state_5.sqlite'));
  db.exec("CREATE TABLE threads(id TEXT,project_id TEXT); CREATE TABLE projects(id TEXT,name TEXT); CREATE TABLE project_roots(project_id TEXT,path TEXT,position INTEGER);");
  db.prepare('INSERT INTO threads VALUES(?,?)').run('main','project-a');
  db.prepare('INSERT INTO projects VALUES(?,?)').run('project-a','样例项目');
  db.prepare('INSERT INTO project_roots VALUES(?,?,?)').run('project-a','/sample/repo',0); db.close();
  const result=await s.connector.ingest();
  assert.equal(scalar(s,'SELECT count(*) n FROM session'),1);
  assert.equal(result.accounting.unparsed??0,0);
  assert.equal(scalar(s,"SELECT count(*) n FROM current_record WHERE session_uid IS NULL AND note IS NOT NULL"),2);
}));
test('legacy child threads without a cutoff use the first turn absent from the parent',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());
  await writeFile(join(s.home,'sessions','rollout-old-child.jsonl'),
    jsonLine('session_meta',{id:'old-child',session_id:'main',parent_thread_id:'main',source:{subagent:{thread_spawn:{parent_thread_id:'main'}}}},0)+
    jsonLine('event_msg',{type:'task_started',turn_id:'t1'},1)+
    jsonLine('event_msg',{type:'task_started',turn_id:'own-old-turn'},2)+
    jsonLine('event_msg',{type:'user_message',message:'自己的输入'},3));
  await s.connector.ingest();
  assert.equal(s.store.db.prepare('SELECT count(*) n FROM turn WHERE session_uid=?').get(sessionUid(s.connector.sourceId,'old-child'))?.n,1);
}));
test('revert segments with the same thread ID keep distinct ordinal ranges and deduplicate response IDs',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());
  await writeFile(join(s.home,'archived_sessions','rollout-revert-main.jsonl'),
    jsonLine('session_meta',{id:'main',session_id:'main',history_base:{thread_id:'main',end_ordinal_exclusive:25}},25)+
    jsonLine('event_msg',{type:'task_started',turn_id:'revert-turn'},26)+
    jsonLine('turn_context',{turn_id:'revert-turn',model:'gpt-revert'},27)+
    jsonLine('token_usage_record',{turn_id:'revert-turn',response_id:'new-response',usage:{input_tokens:10,output_tokens:5}},28));
  await s.connector.ingest();
  assert.equal(scalar(s,'SELECT count(*) n FROM session'),1); assert.equal(scalar(s,'SELECT count(*) n FROM model_call'),2);
  assert.equal(scalar(s,'SELECT count(*) n FROM turn'),2);
}));
test('active revert chain bounds the predecessor and excludes disconnected branches selected by the index',async()=>sandbox(async s=>{
  const root=join(s.home,'sessions','rollout-root.jsonl'),oldBranch=join(s.home,'sessions','rollout-z-old-branch.jsonl'),active=join(s.home,'sessions','rollout-active.jsonl');
  await writeFile(root,
    jsonLine('session_meta',{id:'reverted',session_id:'reverted'},0)+
    jsonLine('event_msg',{type:'task_started',turn_id:'keep'},1)+
    jsonLine('token_usage_record',{turn_id:'keep',response_id:'keep-request',usage:{input_tokens:10,output_tokens:5}},2)+
    jsonLine('event_msg',{type:'task_complete',turn_id:'keep'},3)+
    jsonLine('event_msg',{type:'task_started',turn_id:'undone'},4)+
    jsonLine('token_usage_record',{turn_id:'undone',response_id:'undone-request',usage:{input_tokens:100,output_tokens:50}},5));
  await writeFile(oldBranch,jsonLine('session_meta',{id:'reverted',session_id:'reverted',history_base:{thread_id:'root',end_ordinal_exclusive:4}},4)+
    jsonLine('event_msg',{type:'user_message',turn_id:'old-sibling',message:'discard old sibling'},5));
  await writeFile(active,jsonLine('session_meta',{id:'reverted',session_id:'reverted',history_base:{thread_id:'root',end_ordinal_exclusive:4}},4)+
    jsonLine('event_msg',{type:'task_started',turn_id:'current'},5)+
    jsonLine('token_usage_record',{turn_id:'current',response_id:'current-request',usage:{input_tokens:20,output_tokens:10}},6));
  const index=new DatabaseSync(join(s.home,'state_5.sqlite'));index.exec('CREATE TABLE threads(id TEXT,rollout_path TEXT)');
  index.prepare('INSERT INTO threads VALUES(?,?)').run('reverted',active);index.close();
  const result=await s.connector.ingest();
  assert.equal(result.accounting.unparsed??0,0);assert.equal(scalar(s,'SELECT count(*) n FROM model_call'),2);
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE text='discard old sibling'"),0);
  assert.equal(scalar(s,"SELECT count(*) n FROM model_call WHERE request_id='undone-request'"),0);
  assert.ok(scalar(s,"SELECT count(*) n FROM current_record WHERE note='reverted_history:outside_active_chain'")>=3);
  assert.equal(scalar(s,'SELECT count(*) n FROM turn'),2);
}));
test('legacy rollback excludes the preceding user turn without losing its raw evidence',async()=>sandbox(async s=>{
  await writeFile(s.file,
    jsonLine('session_meta',{id:'legacy-rollback',history_mode:'legacy'},0)+
    jsonLine('event_msg',{type:'task_started',turn_id:'retained'},1)+jsonLine('event_msg',{type:'user_message',message:'retain'},2)+
    jsonLine('token_usage_record',{turn_id:'retained',response_id:'retain-usage',usage:{input_tokens:10,output_tokens:5}},3)+
    jsonLine('event_msg',{type:'task_complete',turn_id:'retained'},4)+
    jsonLine('event_msg',{type:'task_started',turn_id:'removed'},5)+jsonLine('event_msg',{type:'user_message',message:'remove'},6)+
    jsonLine('token_usage_record',{turn_id:'removed',response_id:'remove-usage',usage:{input_tokens:100,output_tokens:50}},7)+
    jsonLine('event_msg',{type:'task_complete',turn_id:'removed'},8)+jsonLine('event_msg',{type:'thread_rolled_back',num_turns:1},9)+
    jsonLine('event_msg',{type:'task_started',turn_id:'resumed'},10)+jsonLine('event_msg',{type:'user_message',message:'resume'},11));
  await s.connector.ingest();
  assert.equal(scalar(s,"SELECT count(*) n FROM event WHERE text='remove'"),0);
  assert.equal(scalar(s,"SELECT count(*) n FROM model_call WHERE request_id='remove-usage'"),0);
  assert.equal(scalar(s,'SELECT count(*) n FROM turn'),2);
  const removed=s.store.db.prepare("SELECT record_uid FROM current_record WHERE ordinal=6").get()!;
  assert.ok((await readRawRecord(s.store,String(removed.record_uid))).toString().includes('remove'));
}));
test('an incomplete zstd frame leaves its cursor unchanged and succeeds after completion',async()=>sandbox(async s=>{
  const bytes=zstdCompressSync(await fixture());
  await writeFile(s.file+'.zst',bytes.subarray(0,-2)); const failed=await s.connector.ingest();
  assert.equal(failed.files_failed,1); assert.equal(scalar(s,'SELECT count(*) n FROM raw_record'),0);
  await appendFile(s.file+'.zst',bytes.subarray(-2)); const result=await s.connector.ingest();
  assert.equal(result.files_failed,0); assert.ok(result.records_added>0);
}));
test('watch coalesces updates and stops cleanly',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());
  const controller=new AbortController(); let updates=0;
  const guard=setTimeout(()=>controller.abort(),3000);
  try {
    await watchCodex(s.connector,{signal:controller.signal,pollMs:30,debounceMs:10,onError:error=>{
      assert.ok(['EMFILE','ENOSYS','EACCES','EPERM'].includes(String((error as NodeJS.ErrnoException).code)));
    },onResult:result=>{
      updates++;
      if (updates===1) void appendFile(s.file,jsonLine('world_state',{full:false,state:{watch_test:true}},40));
      else if (result.records_added===1) controller.abort();
    }});
    assert.ok(updates>=2);
    assert.equal(scalar(s,"SELECT count(*) n FROM current_record WHERE native_type='world_state'"),2);
  } finally {clearTimeout(guard);controller.abort();}
}));
test('CLI discovery stays read-only; ingest, stats, JSONL export and raw retrieval work together',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());
  const run=promisify(execFile),cli=new URL('../src/cli.ts',import.meta.url);
  const command=async(args:string[])=>run(process.execPath,[fileURLToPath(cli),...args]);
  const data=join(s.root,'cli-output');
  const discover=JSON.parse((await command(['discover','--codex-home',s.home])).stdout);
  assert.equal(discover.enabled,false);
  const first=JSON.parse((await command(['ingest','--codex-home',s.home,'--data-dir',data])).stdout);
  assert.ok(first.records_added>0);
  const stats=JSON.parse((await command(['stats','--data-dir',data])).stdout); assert.equal(stats.sessions,1);
  const exported=await command(['export','--data-dir',data,'--session',sessionUid(first.source_id,'main')]);
  assert.ok(exported.stdout.trim().split('\n').every(line=>JSON.parse(line).event_uid));
  const record=JSON.parse(exported.stdout.trim().split('\n')[0]!).record_uid;
  const raw=await command(['raw','--data-dir',data,'--record',record]); assert.ok(JSON.parse(raw.stdout).type);
}));

test('nullable time, native order, and time semantics survive backward clocks without fabricated bounds',async()=>sandbox(async s=>{
  await writeFile(s.file,jsonLine('session_meta',{id:'ordered',timestamp:'2026-10-02T00:00:00Z'},0)+
    JSON.stringify({ordinal:1,type:'event_msg',payload:{type:'item_completed',turn_id:'order-turn',item:{type:'UserMessage',id:'untimed',content:[{type:'text',text:'时间未知'}]}}})+'\n'+
    JSON.stringify({ordinal:2,timestamp:'2026-10-02T00:00:09Z',type:'event_msg',payload:{type:'user_message',turn_id:'order-turn',message:'先写'}})+'\n'+
    JSON.stringify({ordinal:3,timestamp:'2026-10-02T00:00:01Z',type:'event_msg',payload:{type:'user_message',turn_id:'order-turn',message:'后写'}})+'\n'+
    jsonLine('event_msg',{type:'item_completed',turn_id:'order-turn',item:{type:'CommandExecution',id:'no-bounds',command:['pwd'],status:'completed',duration:{secs:1,nanos:0}}},4));
  await s.connector.ingest();
  const unknown=s.store.db.prepare("SELECT ts,attrs,event_path FROM event WHERE text='时间未知'").get()!;
  assert.equal(unknown.ts,null); assert.equal(JSON.parse(String(unknown.attrs)).time.quality,'missing'); assert.ok(unknown.event_path);
  assert.deepEqual(s.store.db.prepare("SELECT text FROM event WHERE text IN ('先写','后写') ORDER BY seq").all().map(row=>row.text),['先写','后写']);
  const tool=s.store.db.prepare("SELECT started_at,ended_at,duration_ms,duration_source,duration_quality FROM tool_call").get()!;
  assert.equal(tool.started_at,null);assert.equal(tool.ended_at,null);assert.equal(tool.duration_ms,1000);assert.equal(tool.duration_source,'reported');
}));
test('cumulative-only usage is a snapshot; missing cache buckets and request identity stay unknown',async()=>sandbox(async s=>{
  await writeFile(s.file,jsonLine('session_meta',{id:'snapshot'},0)+jsonLine('event_msg',{type:'token_count',info:{total_token_usage:{input_tokens:8000,output_tokens:100},last_token_usage:{input_tokens:8000,output_tokens:100}}},1));
  await s.connector.ingest();
  assert.equal(scalar(s,'SELECT count(*) n FROM model_call'),0);assert.equal(scalar(s,'SELECT count(*) n FROM usage_snapshot'),1);
  const row=s.store.db.prepare('SELECT attrs FROM event WHERE kind=\'model.usage\'').get()!;
  const a=JSON.parse(String(row.attrs));assert.equal(a.measurement,'cumulative');assert.equal(a.request_id,null);assert.equal(a.input_tokens,null);assert.equal(a.cache_read_tokens,null);
}));
test('unchanged totals do not erase a new legacy request; complementary direct-tool arguments and states are merged',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture('legacy')+jsonLine('response_item',{type:'function_call',call_id:'another-step',name:'exec_command',arguments:JSON.stringify({cmd:'target-test',workdir:'/target'})},20)+
    jsonLine('event_msg',{type:'token_count',info:{total_token_usage:{input_tokens:100,output_tokens:20},last_token_usage:{input_tokens:30,output_tokens:5}}},21));
  await s.connector.ingest();assert.equal(scalar(s,'SELECT count(*) n FROM model_call'),2);
  const snapshotCount=scalar(s,'SELECT count(*) n FROM usage_snapshot');assert.ok(snapshotCount>=1);
  const second=await fixture();await writeFile(s.file,second);await s.connector.ingest();
  const call=s.store.db.prepare("SELECT attrs FROM event WHERE kind='tool.call' AND call_id='c1'").get()!;
  assert.equal(JSON.parse(String(call.attrs)).arguments.cmd,'pnpm test');
  assert.equal(s.store.db.prepare("SELECT status FROM tool_call WHERE name_raw='exec_command' AND exit_code=2").get()?.status,'failed');
}));
test('record_event represents one native completion contributing multiple events and remains valid on a parent rebuild',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());await s.connector.ingest();
  assert.ok(scalar(s,'SELECT count(*) n FROM (SELECT record_uid FROM record_event GROUP BY record_uid HAVING count(*)>1)')>0);
  assert.equal(scalar(s,'SELECT count(*) n FROM record_event re LEFT JOIN event e USING(event_uid) WHERE e.event_uid IS NULL'),0);
}));
test('v1 staging migration rebuilds nullable L2/L3 without losing archived originals',async()=>sandbox(async s=>{
  const directory=join(s.root,'old-staging');await mkdir(join(directory,'raw'),{recursive:true});
  const native=await fixture(),bytes=Buffer.from(native),oldPath=join(directory,'tandem.db');
  const db=new DatabaseSync(oldPath);db.exec(readFileSync(new URL('../schema/001.sql',import.meta.url),'utf8'));db.exec('PRAGMA user_version=1');
  const source=s.connector.sourceId,file=uid(source,'old-file'),sid=sessionUid(source,'main'),archive=join(directory,'raw','fixture.zst');
  await writeFile(archive,zstdCompressSync(bytes));db.prepare('INSERT INTO source VALUES(?,?,?,?,?,?)').run(source,'codex',s.home,'fixture',1,1);
  db.prepare('INSERT INTO source_file(file_id,source_id,path,role,format,generation) VALUES(?,?,?,?,?,1)').run(file,source,s.file,'transcript','jsonl');
  db.prepare('INSERT INTO archive_chunk VALUES(?,?,?,?,?,?)').run(file,1,0,bytes.length,hash(bytes),archive);
  let turn:string|null=null,offset=0;
  for (const [index,line] of native.trim().split('\n').entries()) {
    const data=JSON.parse(line),raw=Buffer.from(line+'\n');turn=data.payload.turn_id??turn;
    const subtype=data.payload.type?':'+data.payload.type:'';
    db.prepare('INSERT INTO raw_record VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run(uid(file,index),file,1,index+1,data.ordinal,offset,raw.length,hash(raw),data.type+subtype,'fixture',Date.parse(data.timestamp),sid,turn,JSON.stringify(sanitize(data)),'ignored',null,null);
    offset+=raw.length;
  }
  db.close();const migrated=new ConnectorStore(directory);
  try {
    assert.equal(migrated.db.prepare('PRAGMA user_version').get()?.user_version,2);
    assert.equal(migrated.db.prepare('SELECT count(*) n FROM model_call').get()?.n,1);
    assert.deepEqual(await readRawRecord(migrated,uid(file,0)),Buffer.from(native.split('\n')[0]+'\n'));
  } finally {migrated.close();}
}));
test('a redaction upgrade re-cleans cached L1 and republishes L2 without touching L0',async()=>sandbox(async s=>{
  await writeFile(s.file,await fixture());await s.connector.ingest();
  const row=s.store.db.prepare("SELECT record_uid,body FROM current_record WHERE native_type='response_item:function_call' LIMIT 1").get()!;
  const body=JSON.parse(String(row.body));body.payload.arguments=JSON.stringify({token:'opaque-old-cache-secret'});
  s.store.db.prepare('UPDATE raw_record SET body=? WHERE record_uid=?').run(JSON.stringify(body),String(row.record_uid));
  s.store.db.prepare("UPDATE pipeline_version SET version='codex-redact/0.2.0' WHERE component='redaction'").run();
  const original=await readRawRecord(s.store,String(row.record_uid));
  const upgraded=new ConnectorStore(s.store.directory);
  try {
    assert.ok(!String(upgraded.db.prepare('SELECT body FROM raw_record WHERE record_uid=?').get(String(row.record_uid))?.body).includes('opaque-old-cache-secret'));
    assert.ok(!JSON.stringify(upgraded.db.prepare('SELECT attrs,ext FROM event').all()).includes('opaque-old-cache-secret'));
    assert.deepEqual(await readRawRecord(upgraded,String(row.record_uid)),original);
  } finally {upgraded.close();}
}));
