#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { homedir } from 'node:os';
import { join, resolve, dirname, basename } from 'node:path';
import { realpath, access } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { once } from 'node:events';
import { DatabaseSync } from 'node:sqlite';
import { CodexConnector } from './ingest.ts';
import { ConnectorStore, SCHEMA_VERSION } from './store.ts';
import { discoverCodex, defaultCodexHome, within } from './discovery.ts';
import { watchCodex } from './watch.ts';
import { readRawRecord } from './archive.ts';
import { redact } from './privacy.ts';

const help=`Tandem Codex Connector — 本地只读采集与标准化

  tandem-ingest init     [--data-dir PATH]
  tandem-ingest discover [--codex-home PATH]
  tandem-ingest ingest   [--codex-home PATH] [--data-dir PATH] [--file PATH ...] [--no-index]
  tandem-ingest watch    [--codex-home PATH] [--data-dir PATH]
  tandem-ingest stats    [--data-dir PATH]
  tandem-ingest rebuild  [--data-dir PATH]
  tandem-ingest export   --session UID [--data-dir PATH] [--output FILE]
  tandem-ingest raw      --record UID [--data-dir PATH]

discover 只列来源与文件数量，不导入。ingest/watch 明确启用指定来源。
默认来源为 CODEX_HOME 或 ~/.codex；默认 staging 输出在 ~/Library/Application Support/Tandem/connectors/codex。
export 输出脱敏标准事件 JSONL；raw 明确请求所选记录的原始字节（可能含敏感内容）。
已有导出文件不会覆盖。退出码 2 表示存在待读取文件或无法解析的记录。`;
async function canonicalDestination(path:string):Promise<string> {
  try { return await realpath(path); }
  catch { const parent=dirname(path); return parent===path?path:join(await canonicalDestination(parent),basename(path)); }
}
async function main():Promise<void> {
  const {values,positionals}=parseArgs({allowPositionals:true,options:{
    'codex-home':{type:'string'},'data-dir':{type:'string'},session:{type:'string'},record:{type:'string'},output:{type:'string'},help:{type:'boolean',short:'h'}
    ,file:{type:'string',multiple:true},'no-index':{type:'boolean'}
  }});
  const command=positionals[0];
  if (values.help || !command) { console.log(help); return; }
  if (positionals.length!==1 || !['init','discover','ingest','watch','stats','export','raw','rebuild'].includes(command)) throw new Error('Unknown command; use --help');
  const directory=resolve(values['data-dir']??join(homedir(),'Library','Application Support','Tandem','connectors','codex'));
  const root=values['codex-home']??defaultCodexHome();
  if (command==='init') {
    const home=await canonicalDestination(resolve(root));
    if (within(home,await canonicalDestination(directory))) throw new Error('--data-dir must be outside CODEX_HOME');
    const store=new ConnectorStore(directory);
    try {console.log(JSON.stringify({db_schema_version:SCHEMA_VERSION,input_contract:'analysis-input-v1',directory}));}finally{store.close();}return;
  }
  if (command==='discover') {
    const result=await discoverCodex(root);
    console.log(JSON.stringify({agent:'codex',root:result.root,transcript_files:result.files.length,index_path:result.index_path,maintenance:result.maintenance,enabled:false},null,2)); return;
  }
  if (command==='ingest'||command==='watch') {
    const home=await realpath(root);
    if (within(home,await canonicalDestination(directory))) throw new Error('--data-dir must be outside CODEX_HOME');
    const store=new ConnectorStore(directory),connector=new CodexConnector(store,home);
    const ingestOptions={files:values.file,includeMetadata:!values['no-index']};
    try {
      if (command==='ingest') {
        const result=await connector.ingest(ingestOptions); console.log(JSON.stringify(result,null,2));
        if (result.files_failed || result.rebuild_failed || result.accounting.unparsed) process.exitCode=2;
      } else {
        const controller=new AbortController();
        const stop=():void=>controller.abort(); process.once('SIGINT',stop); process.once('SIGTERM',stop);
        let first=true;
        try {
          await watchCodex(connector,{signal:controller.signal,ingest:ingestOptions,onResult:result=>{
            if (first||result.files_changed||result.files_failed||result.maintenance_skipped) console.log(JSON.stringify(result)); first=false;
          },onError:error=>console.error(redact(String(error)))});
        } finally { process.removeListener('SIGINT',stop); process.removeListener('SIGTERM',stop); }
      }
    } finally { store.close(); }
    return;
  }
  await access(join(directory,'tandem.db'));
  if (command==='rebuild') {
    const store=new ConnectorStore(directory);
    try {console.log(JSON.stringify({sessions_rebuilt:store.rebuild(),db_schema_version:SCHEMA_VERSION,input_contract:'analysis-input-v1'}));}
    finally {store.close();}return;
  }
  if (command==='raw') {
    if (!values.record) throw new Error('raw requires --record');
    const store=new ConnectorStore(directory);
    try { process.stdout.write(await readRawRecord(store,values.record)); } finally {store.close();} return;
  }
  const db=new DatabaseSync(join(directory,'tandem.db'),{readOnly:true});
  try {
    db.exec('PRAGMA query_only=ON; PRAGMA busy_timeout=5000; BEGIN');
    if (command==='stats') {
      const count=(table:string)=>db.prepare(`SELECT count(*) AS n FROM ${table}`).get()?.n;
      console.log(JSON.stringify({sessions:count('session'),events:count('event'),turns:count('turn'),tools:count('tool_call'),model_calls:count('model_call'),
        usage_snapshots:count('usage_snapshot'),db_schema_version:SCHEMA_VERSION,input_contract:'analysis-input-v1',
        versions:db.prepare('SELECT * FROM pipeline_version').all(),sample_boundary:db.prepare('SELECT * FROM source_boundary').all(),
        main_model_usage:db.prepare(`SELECT model_id,count(*) AS calls,sum(input_tokens) AS known_input_tokens,sum(input_tokens IS NULL) AS input_unknown_calls,
          sum(cache_read_tokens) AS known_cache_read_tokens,sum(cache_read_tokens IS NULL) AS cache_read_unknown_calls,
          sum(output_tokens) AS known_output_tokens,sum(output_tokens IS NULL) AS output_unknown_calls FROM main_model_usage GROUP BY model_id`).all(),
        accounting:db.prepare('SELECT disposition,count(*) AS n FROM current_record GROUP BY disposition').all(),
        diagnostics:db.prepare('SELECT code,count(*) AS n FROM diagnostic GROUP BY code').all()},null,2));
    } else {
      if (!values.session) throw new Error('export requires --session');
      if (!db.prepare('SELECT 1 FROM session WHERE session_uid=?').get(values.session)) throw new Error('Unknown session');
      const output=values.output?resolve(values.output):null;
      if (output) for (const source of db.prepare('SELECT root_path FROM source').all()) {
        if (within(String(source.root_path),await canonicalDestination(output))) throw new Error('Cannot export into an Agent source directory');
      }
      const stream=output?createWriteStream(output,{flags:'wx',mode:0o600}):process.stdout;
      const failure=(error:Error):void=>{console.error(redact(error.message));process.exitCode=1;};
      stream.on('error',failure);
      try {
        for (const event of db.prepare('SELECT * FROM event WHERE session_uid=? ORDER BY seq').iterate(values.session)) {
          const row={...event,attrs:JSON.parse(String(event.attrs)),ext:JSON.parse(String(event.ext)),native_key:JSON.parse(String(event.native_key))};
          if (!stream.write(JSON.stringify(row)+'\n')) await once(stream,'drain');
        }
        if (output) { stream.end(); await once(stream,'finish'); }
      } finally { stream.removeListener('error',failure); }
    }
    db.exec('COMMIT');
  } finally {db.close();}
}
main().catch(error=>{console.error(redact(error instanceof Error?error.message:String(error)));process.exitCode=1;});
