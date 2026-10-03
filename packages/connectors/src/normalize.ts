import { object, string, number, array } from './types.ts';
import type { Obj, Json, RawRecord, StandardEvent, Disposition } from './types.ts';
import { uid, hash, sessionUid, timestamp, durationMs, pathValue, stableJson } from './util.ts';
import { validateEvent } from './contract.ts';
import { projectFor } from './project.ts';
import { commandHead } from './shell.ts';
import { redact } from './privacy.ts';
import type { ConnectorStore } from './store.ts';
import { basename } from 'node:path';

function activeHistory(store:ConnectorStore,source:string,metas:Map<string,Obj>,index:Obj):Map<string,number>|null {
  if(metas.size<2)return null;
  const aliases=new Map<string,string>(),files=new Map<string,{path:string,mtime:string}>();
  for(const [file] of metas){
    const row=store.file(file)!;const stem=basename(row.path).replace(/\.zst$/,'').replace(/\.jsonl$/,'');
    const native=stem.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi)?.at(-1);
    aliases.set(native??stem.replace(/^rollout-/,''),file);files.set(file,{path:row.path,mtime:row.mtime_ns??'0'});
  }
  const parents=new Map<string,string>();
  for(const [file,meta] of metas){const parent=aliases.get(string(object(meta.history_base).thread_id)??'');if(parent&&parent!==file)parents.set(file,parent);}
  if(!parents.size)return null;
  const pointed=new Set(parents.values()),sinks=[...metas.keys()].filter(file=>!pointed.has(file));
  const currentPath=string(index.rollout_path);
  let active=currentPath?[...files].find(([,file])=>file.path===currentPath||basename(file.path).replace(/\.zst$/,'')===basename(currentPath).replace(/\.zst$/,''))?.[0]:undefined;
  if(!active){
    active=sinks.sort((a,b)=>{
      const pa=basename(files.get(a)!.path),pb=basename(files.get(b)!.path);
      return pa.localeCompare(pb)||(BigInt(files.get(a)!.mtime)>BigInt(files.get(b)!.mtime)?1:-1);
    }).at(-1);
    if(sinks.length>1)store.diagnostic(source,'active_history_inferred','Multiple history branches; selected the latest native filename pending current index');
  }
  if(!active)return null;
  const bounds=new Map<string,number>();let current:string|undefined=active,limit=Infinity;
  while(current&&!bounds.has(current)){
    bounds.set(current,limit);
    const meta=metas.get(current)!;const base=object(meta.history_base);
    limit=Math.min(limit,number(base.end_ordinal_exclusive)??Infinity);current=parents.get(current);
  }
  return bounds;
}
function legacyRollbackRows(store:ConnectorStore,session:string,accepted:(row:RawRecord)=>boolean):Set<string> {
  const rows=new Map<string,RawRecord[]>();
  for(const row of store.records(session))if(accepted(row)){const values=rows.get(row.file_id)??[];values.push(row);rows.set(row.file_id,values);}
  const excluded=new Set<string>();
  for(const values of rows.values()){
    const starts:{ordinal:number,turn:string|null,human:boolean}[]=[];
    for(const row of values){
      const p=object(bodyOf(row).payload),type=string(p.type);
      if(['task_started','turn_started'].includes(type??''))starts.push({ordinal:row.ordinal,turn:row.turn_native_id,human:false});
      if(type==='user_message'||(type==='item_completed'&&object(p.item).type==='UserMessage')){
        const latest=starts.at(-1);
        if(!latest|| (row.turn_native_id!==null&&latest.turn!==row.turn_native_id) || (row.turn_native_id===null&&latest.human))starts.push({ordinal:row.ordinal,turn:row.turn_native_id,human:true});
        else latest.human=true;
      }
      if(type==='thread_rolled_back'){
        const count=number(p.num_turns),users=starts.filter(start=>start.human);
        if(count!==null&&count>0&&Number.isInteger(count)&&users.length){
          const cutoff=users[Math.max(0,users.length-count)]!.ordinal;
          for(const prior of values)if(prior.ordinal>=cutoff&&prior.ordinal<row.ordinal)excluded.add(prior.record_uid);
          while(starts.length&&starts.at(-1)!.ordinal>=cutoff)starts.pop();
        }
      }
    }
  }
  return excluded;
}

interface Candidate { event: StandardEvent; key: string; priority: number; record: RawRecord; position: number; slot: number; }
interface Context {
  source: string; session: string; native: string; kind: string; meta: Obj;
  uiIds: Set<string>; uiMessages: Map<string,string>; exactByTurn: Map<string,string>;
  fileMeta: Map<string,Obj>; settings: Map<string,Obj>; wrapperByTurn: Map<string,{ordinal:number,id:string}[]>;
  recordSettings: Map<string,Obj>;
  legacyRequestByRecord: Map<string,string>;
  snapshotByRecord: Map<string,string>;
  /** True when the session carries per-response token_usage_record rows (exact accounting). */
  hasExactUsage: boolean;
  /** Counter cycle of each legacy token_count total; a new cycle starts when the native total falls. */
  snapshotCycleByRecord: Map<string,{cycle:number,reset:boolean}>;
}
const nonNull = (value: Record<string,Json|undefined>): Obj => Object.fromEntries(Object.entries(value).filter(([,v])=>v!==null&&v!==undefined)) as Obj;
function bodyOf(row: RawRecord): Obj { return row.body ? object(JSON.parse(row.body)) : {}; }
function clearProjection(store:ConnectorStore,session:string):void {
  store.db.prepare('DELETE FROM record_event WHERE event_uid IN (SELECT event_uid FROM event WHERE session_uid=?)').run(session);
  store.db.prepare('DELETE FROM event_context WHERE event_uid IN (SELECT event_uid FROM event WHERE session_uid=?)').run(session);
  for(const table of ['usage_snapshot','session_feature','link','turn','tool_call','model_call','event'])store.db.prepare(`DELETE FROM ${table} WHERE session_uid=?`).run(session);
}
function content(value: unknown): string {
  if (typeof value === 'string') return value;
  return array(value).map(item => string(object(item).text) ?? string(object(item).summary_text) ?? '').filter(Boolean).join('\n');
}
function contentChars(value:unknown):number {
  if(typeof value==='string')return Array.from(value).length;
  return array(value).reduce<number>((sum,item)=>sum+Array.from(string(object(item).text)??string(object(item).summary_text)??'').length,0);
}
function messageKey(role: string, turn: string | null, phase: string | null, text: string): string { return uid(role,turn,phase,text); }
function classify(meta: Obj, index: Obj, imported: boolean): string {
  if (imported) return 'import';
  const source = object(meta.source), subagent = object(source.subagent);
  const kind = string(index.thread_source) ?? string(meta.thread_source);
  if (kind === 'guardian_review' || subagent.other === 'guardian' || source.subagent === 'review') return 'review';
  if (kind === 'automation') return 'automation';
  if (kind === 'memory_consolidation' || source.subagent==='memory_consolidation') return 'auxiliary';
  if (source.subagent==='compact') return 'auxiliary';
  if (kind === 'subagent' || subagent.thread_spawn || string(meta.parent_thread_id)) return 'subagent';
  if (kind && !['user','realtime_voice'].includes(kind)) return 'auxiliary';
  return 'main';
}
function origin(ctx: Context): string { return ctx.kind === 'automation' ? 'automation' : ctx.kind === 'main' ? 'human' : 'injected'; }
/**
 * Native tool name -> category. Names come from Codex built-in tools, collab (multi-agent) tools and
 * Desktop extensions observed in real rollouts; extend the table when unknown_tool_name diagnostics appear.
 * Code-mode wrappers (custom_tool_call exec/wait) are categorized 'wrapper' by the caller.
 */
const TOOL_CATEGORIES: Record<string,readonly string[]> = {
  shell: ['exec_command','local_shell','local_shell_call','shell','shell_command','bash','CommandExecution','write_stdin'],
  'file.edit': ['apply_patch','FileChange','edit_file','append_to_file','write_file'],
  'file.read': ['read_file'],
  'image.view': ['view_image','ImageView'],
  'image.generate': ['image_gen.generation','image_generation_call','ImageGeneration'],
  subagent: ['spawn_agent','send_message','send_input','followup_task','wait_agent','wait','list_agents','interrupt_agent','close_agent',
    'resume_agent','send_message_to_thread','SubAgentActivity','CollabAgentToolCall'],
  plan: ['update_plan','TodoWrite'],
  ask_user: ['request_user_input','request_user_input_async'],
  'web.search': ['web.search','web_search','web_search_call','WebSearch'],
  'tool.search': ['tool_search_call','tool_search'],
  sleep: ['clock.sleep'],
  automation: ['automation_update'],
};
const CATEGORY_BY_NAME = new Map(Object.entries(TOOL_CATEGORIES).flatMap(([category,names])=>names.map(name=>[name,category] as const)));
export function toolCategory(name: string): string {
  if (name.startsWith('mcp__')) return 'mcp';
  return CATEGORY_BY_NAME.get(name) ?? (/^web[._]?(fetch|open)/i.test(name) ? 'web.fetch' : 'other');
}
/**
 * Codex writes exit_code -1 when no process exit status exists (the command was declined, interrupted
 * or never spawned); the native status then decides, so -1 alone is not a failure.
 */
function status(value: unknown, exit: number | null = null, isError = false): string {
  if (isError || (exit !== null && exit !== 0 && exit !== -1)) return 'failed';
  const raw = string(value)?.replace('inProgress','in_progress');
  return raw && ['completed','failed','declined','interrupted','in_progress'].includes(raw) ? raw : 'unknown';
}
function usageAttrs(usage: Obj, settings: Obj, ctx: Context, request: string, accounting: string): Obj {
  const token=(v:unknown):number|null=>{const n=number(v);return n!==null&&Number.isSafeInteger(n)&&n>=0?n:null;};
  // OpenAI usage has no cache-write bucket (only input_tokens_details.cached_tokens); Codex adds
  // cache_write_input_tokens for providers that bill writes. An absent field therefore means 0, flagged.
  const writeAbsent=!('cache_write_input_tokens' in usage);
  const totalInput=token(usage.input_tokens),read=token(usage.cached_input_tokens),write=writeAbsent?0:token(usage.cache_write_input_tokens);
  const fresh=totalInput!==null&&read!==null&&write!==null?totalInput-read-write:null;
  return {provider:string(settings.model_provider_id)??string(ctx.meta.model_provider),model:string(settings.model),model_raw:string(settings.model),
    effort:string(settings.effort)??string(settings.reasoning_effort),effort_raw:string(settings.effort)??string(settings.reasoning_effort),request_id:accounting==='exact'?request:null,
    input_tokens:fresh!==null&&fresh>=0?fresh:null,cache_read_tokens:read,cache_write_tokens:write,
    output_tokens:token(usage.output_tokens),reasoning_tokens:token(usage.reasoning_output_tokens),
    accounting,estimated:ctx.kind==='import',native_usage:usage,reported:usage,usage_scope:'call',measurement:'delta',coverage:'self',
    ...(writeAbsent?{cache_write_assumed_zero:true}:{}),request_key:[ctx.source,ctx.session,request],purpose:ctx.kind==='review'?'review':ctx.kind==='subagent'?'subagent':ctx.kind==='auxiliary'?'auxiliary':'main'};
}
/** Context-window saturation placeholder emitted by old Codex builds; it is not usage. */
function syntheticTotal(info: Obj): boolean {
  const total=object(info.total_token_usage);
  return number(total.total_tokens)===number(info.model_context_window) && (number(total.input_tokens)??0)===0 && (number(total.output_tokens)??0)===0;
}
function snapshotAttrs(usage: Obj, ctx: Context, counter: string, cycle: {cycle:number,reset:boolean}|null): Obj {
  const attrs=usageAttrs(usage,{},ctx,'snapshot','snapshot');
  delete attrs.request_key; attrs.request_id=null; attrs.usage_scope='session_snapshot'; attrs.measurement='cumulative';
  attrs.snapshot_key=uid(ctx.source,ctx.session,'session_snapshot','unknown_model',string(ctx.meta.model_provider),counter,...(cycle&&cycle.cycle>0?[cycle.cycle]:[]));
  attrs.counter_cycle=cycle?`${counter}:${cycle.cycle}`:counter;
  if (cycle?.reset) attrs.reset=true;
  attrs.model=null;attrs.model_raw=null;attrs.effort=null;attrs.effort_raw=null;attrs.coverage='self';
  return attrs;
}
/** A string tool output is already the event text; attrs keep only structured (non-string) outputs. */
function structured(value: Json | undefined): Json | undefined { return typeof value==='string' ? undefined : value; }
function mapRecord(row: RawRecord, ctx: Context): Candidate[] {
  const body = bodyOf(row), p = object(body.payload), type = string(body.type) ?? '', subtype = string(p.type) ?? '';
  const result: Candidate[] = [];
  const turn = row.turn_native_id, settings = ctx.recordSettings.get(row.record_uid) ?? {};
  const defaultTime = row.ts;
  function emit(kind: string, actor: string, text: string | null, attrs: Obj = {}, key = `record:${row.record_uid}:${kind}`, priority = 10,
    native: string | null = null, call: string | null = null, ts: number|null = defaultTime, selectedField: string|null = null, semantics='written'): void {
    let sourceField=selectedField;
    const reported:Obj={};
    if (body.timestamp!==undefined) reported.timestamp=body.timestamp;
    for (const field of ['timestamp','started_at','completed_at','started_at_ms','completed_at_ms']) if (p[field]!==undefined) reported[`payload.${field}`]=p[field]!;
    if (!sourceField && ts!==null) sourceField=timestamp(body.timestamp)!==null?'timestamp':timestamp(p.timestamp)!==null?'payload.timestamp':timestamp(p.updated_at)!==null?'payload.updated_at':null;
    if (!sourceField) ts=null;
    const eventPath=kind==='model.usage'?`usage.${attrs.usage_scope==='call'?'call':'session_snapshot'}`:kind==='tool.call'||kind==='tool.result'?kind:`derived.${kind}`;
    const nativeKey=[ctx.source,ctx.session,key];
    const time:Obj={source_field:ts===null?null:sourceField,semantics:ts===null?'unknown':semantics,quality:ts===null?'missing':'reported',reported};
    const shared=nonNull({model_raw:string(settings.model),provider:string(settings.model_provider_id)??string(ctx.meta.model_provider),effort_raw:string(settings.effort)??string(settings.reasoning_effort),native_turn_id:turn});
    result.push({key,priority,record:row,position:row.ordinal,slot:result.length,event:{event_uid:uid(nativeKey,kind,eventPath),native_key:nativeKey,event_path:eventPath,contract_version:1,mapper_version:'codex-connector/0.2.1',session_uid:ctx.session,seq:0,ts,kind,actor,
      turn_uid:turn ? uid(ctx.session,'turn',turn) : null,parent_uid:null,call_id:call,text,text_truncated:text?.includes('<truncated:sha256:') ? 1 : 0,
      attrs:{...shared,...attrs,time,order:{quality:'reported',basis:'native_ordinal_or_line'}},ext:{native_type:row.native_type},record_uid:row.record_uid,native_id:native}});
  }
  function message(role: string, text: string, id: string | null, phase: string | null, priority: number, isResponse = false, measuredChars=Array.from(text).length): void {
    const signature = messageKey(role,turn,phase,text);
    const uiKey = ctx.uiMessages.get(signature) ?? ctx.uiMessages.get(messageKey(role,turn,null,text));
    const key = isResponse ? (id && ctx.uiIds.has(id) ? stableJson(['message','native',id]) : uiKey ?? (id ? stableJson(['message','native',id]) : stableJson(['message','signature',signature])))
      : id ? stableJson(['message','native',id]) : stableJson(['message','legacy',ctx.session,row.sha256]);
    if (role === 'user' && isResponse && !uiKey) {
      emit('context.inject','harness',text,{origin:'injected',role},`injection:${row.record_uid}`); return;
    }
    const complete=!text.includes('<truncated:sha256:')&&!text.includes('<redacted:');
    const measured:Obj={message_digest:complete?hash(text):null,original_chars:complete?measuredChars:null,input_format:role==='user'?'prompt':null,
      writing_measurements:role==='assistant'&&complete?{reply:{chars:measuredChars,surface:'content_blocks',quality:'measured',complete:true},summary:null,body:null}:null,artifact_body_present:null};
    emit(role==='user' ? 'message.user' : 'message.assistant',role==='user' && origin(ctx)==='human' ? 'human' : role==='user' ? 'harness' : 'assistant',text,
      {...(role==='user' ? {origin:origin(ctx)} : nonNull({phase})),...measured},key,priority,id);
  }
  function tool(id: string, name: string, argumentsValue: Json, output: Json | undefined, rawStatus: unknown,
    exit: number | null, duration: number | null, extra: Obj = {}, priority = 30, started: number | null = null, ended: number|null = null, durationSource='unknown'): void {
    const isError = Boolean(object(output).isError) || Boolean(extra.is_error);
    const state = status(rawStatus,exit,isError);
    const {is_error:_error,...callExtra}=extra;
    const digestValue=stableJson(argumentsValue),digestKnown=argumentsValue!==null&&!digestValue.includes('<truncated:sha256:')&&!digestValue.includes('<redacted:')&&!digestValue.includes('<opaque:');
    emit('tool.call','assistant',null,{name,category:callExtra.is_wrapper?'wrapper':toolCategory(name),arguments:argumentsValue,...callExtra,argument_digest:digestKnown?hash(digestValue):null,
      argument_digest_scope:digestKnown?'canonical_redacted':'unavailable'},stableJson(['tool',turn,id,'call']),priority,id,id,started ?? defaultTime,started!==null?'payload.started_at_ms':null,started!==null?'started':'written');
    if (output !== undefined || rawStatus !== undefined) emit('tool.result','tool',typeof output==='string' ? output : content(object(output).content) || null,
      {...nonNull({name,status:state,exit_code:exit,duration_ms:duration,started_at:started,ended_at:ended,is_error:isError,output:structured(output)}),
        duration_source:duration!==null?durationSource:'unknown',duration_quality:duration!==null?'reported':'missing',status_scope:callExtra.is_wrapper?'outer_script':toolCategory(name)==='shell'?'command':'tool'},
      stableJson(['tool',turn,id,'result']),priority,id,id,ended??defaultTime,ended!==null?'payload.completed_at_ms':null,ended!==null?'completed':'written');
    if (state==='declined') emit('permission.decision','harness',null,{decision:'denied',source:'unavailable'},`permission:${turn}:${id}`,priority,id,id);
  }
  if (type === 'session_meta') {
    emit('session.meta','harness',null,nonNull({cwd:string(p.cwd),provider:string(p.model_provider),history_mode:string(p.history_mode),thread_source:string(p.thread_source),metadata:p}),`meta:${row.record_uid}`,10,string(p.id),null,timestamp(p.timestamp)??defaultTime,timestamp(p.timestamp)!==null?'payload.timestamp':null,timestamp(p.timestamp)!==null?'created':'written');
    if (p.forked_from_id || p.history_base) emit('branch','harness',null,nonNull({forked_from:string(p.forked_from_id),ordinal_exclusive:number(p.forked_from_ordinal_exclusive),history_base:p.history_base as Obj}),`branch:${row.record_uid}`);
  } else if (type === 'turn_context') {
    emit('session.meta','harness',null,nonNull({cwd:string(p.cwd),model:string(p.model),effort:string(p.effort),timezone:string(p.timezone),approval_policy:p.approval_policy,
      approvals_reviewer:string(p.approvals_reviewer),sandbox_policy:p.sandbox_policy,metadata:p}),`context:${row.record_uid}`);
  } else if (type === 'state_index') {
    emit('session.meta','harness',null,nonNull({cwd:string(p.cwd),model:string(p.model),effort:string(p.reasoning_effort),metadata:p}),`index:${ctx.native}`);
    if (p.name || p.title || p.preview) emit('session.title','harness',string(p.name) ?? string(p.title) ?? string(p.preview),{source:p.name?'threads.name':'threads.title'},`title:index:${ctx.native}`,p.name?40:10);
  } else if (type === 'title_index') {
    emit('session.title','harness',string(p.thread_name) ?? string(p.name) ?? string(p.title),{source:'session_index'},`title:index:${ctx.native}`,20);
  } else if (type === 'spawn_edge') {
    emit('session.meta','harness',null,{metadata:p},`edge:${ctx.native}`);
  } else if (type === 'import_ledger') {
    emit('link','harness',null,{kind:'external_import',ref:string(p.source_path) ?? string(p.content_sha256) ?? 'unknown'},`import:${ctx.native}`);
  } else if (type === 'world_state') {
    emit('context.inject','harness',null,{origin:'injected',context_type:'world_state',context:p},`world:${row.record_uid}`);
  } else if (type === 'compacted') {
    emit('context.compaction','harness',string(p.message),nonNull({compaction_response_id:string(p.compaction_response_id),window_id:p.window_id,
      window_number:number(p.window_number),replacement_count:array(p.replacement_history).length}),`compaction:${string(p.compaction_response_id) ?? row.record_uid}`);
  } else if (type === 'token_usage_record') {
    const request = string(p.response_id) ?? row.record_uid;
    const attrs=usageAttrs(object(p.usage),settings,ctx,request,'exact');attrs.request_id=string(p.response_id);
    emit('model.usage','harness',null,attrs,`usage:${request}`,40,string(p.response_id));
    // thread_token_usage is the native running total of this thread; unlike token_count's
    // total_token_usage it does not restart inside a session, so it is the authoritative snapshot.
    const thread=object(p.thread_token_usage);
    if (Object.keys(thread).length) emit('model.usage','harness',null,snapshotAttrs(thread,ctx,'thread_token_usage',null),`thread-usage:${request}`,40);
  } else if (type === 'response_item') {
    const id = string(p.id), call = string(p.call_id) ?? id ?? row.record_uid;
    if (subtype === 'message') {
      const role = string(p.role);
      if (role==='user' || role==='assistant') message(role,content(p.content),id,string(p.phase),10,true,contentChars(p.content));
      else emit('context.inject','harness',content(p.content),{origin:'injected',role:role ?? 'developer'},`injection:${row.record_uid}`);
    } else if (subtype === 'reasoning') {
      emit('reasoning','assistant',content(p.summary) || content(p.content),{encrypted:Boolean(p.encrypted_content),summary:array(p.summary),format:content(p.summary)?'summary':p.encrypted_content?'encrypted':'text'},id?`reasoning:${id}`:`reasoning:${row.record_uid}`,10,id);
    } else if (['function_call','custom_tool_call','local_shell_call','tool_search_call','web_search_call','image_generation_call'].includes(subtype)) {
      const name = string(p.name) ?? subtype;
      let args: Json = p.arguments ?? p.action ?? p.input ?? null;
      if (typeof args==='string' && subtype==='function_call') { try { args=JSON.parse(args) as Json; } catch { /* native string retained */ } }
      const wrapper = subtype==='custom_tool_call' && ['exec','wait'].includes(name);
      const shellArgs=!wrapper&&toolCategory(name)==='shell'?object(args):{};
      const line=shellArgs.cmd??shellArgs.command??null;
      tool(call,name,args,undefined,undefined,null,null,nonNull({is_wrapper:wrapper,command_head:line===null?null:commandHead(line),
        command_line:typeof line==='string'?line:Array.isArray(line)&&line.length?line.map(String).join(' '):null,input:subtype==='custom_tool_call'?string(p.input):null,
        attribution:object(body.metadata),mcp_server:name.startsWith('mcp__')?name.split('__')[1]:null,mcp_tool:name.startsWith('mcp__')?name.split('__').slice(2).join('__'):null}),10);
    } else if (['function_call_output','custom_tool_call_output','tool_search_output'].includes(subtype)) {
      const name = string(p.name) ?? 'unknown';
      emit('tool.result','tool',typeof p.output==='string' ? p.output : content(p.output),{name,status:'unknown',...nonNull({output:structured(p.output ?? p.tools ?? null)})},stableJson(['tool',turn,call,'result']),10,call,call);
    } else if (['compaction','compaction_summary','context_compaction'].includes(subtype)) {
      emit('context.compaction','harness',null,{},`compaction:${id ?? row.record_uid}`);
    } else if (subtype==='agent_message') {
      emit('message.user','subagent',content(p.content),{origin:'peer'},`peer:${id ?? row.record_uid}`,20,id);
    } else emit('unknown','harness',null,{native_type:row.native_type});
  } else if (type === 'event_msg') {
    if (['task_started','turn_started'].includes(subtype)) {
      emit('turn.start','harness',null,nonNull({trigger:ctx.kind==='automation'?'automation':ctx.kind==='subagent'?'peer':'human',
        started_at:number(p.started_at)===null?null:Math.round(number(p.started_at)!*1000),model_context_window:number(p.model_context_window)}),`turn:${turn}:start`,30,null,null,number(p.started_at)===null?defaultTime:Math.round(number(p.started_at)!*1000),number(p.started_at)!==null?'payload.started_at':null,number(p.started_at)!==null?'started':'written');
    } else if (['task_complete','turn_complete','turn_aborted'].includes(subtype)) {
      const state = p.error ? 'failed' : subtype==='turn_aborted' ? 'interrupted' : 'completed';
      emit('turn.end','harness',null,nonNull({status:state,duration_ms:number(p.duration_ms),ttft_ms:number(p.time_to_first_token_ms),error:p.error,reason:string(p.reason)}),`turn:${turn}:end`,30,null,null,
        number(p.completed_at)===null?defaultTime:Math.round(number(p.completed_at)!*1000),number(p.completed_at)!==null?'payload.completed_at':null,number(p.completed_at)!==null?'completed':'written');
      if (p.error) emit('error','harness',null,{error:p.error},`error:${row.record_uid}`);
    } else if (subtype==='user_message' || subtype==='agent_message') message(subtype==='user_message'?'user':'assistant',string(p.message) ?? content(p.content),string(p.id),string(p.phase),30,false,contentChars(p.message??p.content));
    else if (subtype==='agent_reasoning' || subtype==='agent_reasoning_raw_content') emit('reasoning','assistant',string(p.text),{encrypted:false},`reasoning:${string(p.id) ?? row.record_uid}`,20,string(p.id));
    else if (subtype==='token_count') {
      const info = object(p.info), total = object(info.total_token_usage), last = object(info.last_token_usage);
      const synthetic = syntheticTotal(info);
      const request=ctx.legacyRequestByRecord.get(row.record_uid);
      if (Object.keys(last).length && !synthetic && request) emit('model.usage','harness',null,usageAttrs(last,settings,ctx,request,'legacy'),`legacy-usage:${request}`,10);
      // Legacy totals only when no exact thread_token_usage exists: total_token_usage restarts inside
      // a session (resume/compaction), so each restart opens a new counter cycle and snapshot_key.
      if (Object.keys(total).length && !synthetic && !ctx.hasExactUsage) {
        const cycle=ctx.snapshotCycleByRecord.get(row.record_uid)??{cycle:0,reset:false};
        emit('model.usage','harness',null,snapshotAttrs(total,ctx,'thread_total',cycle),ctx.snapshotByRecord.get(row.record_uid)??`snapshot:${row.record_uid}`,20);
      }
      if (p.rate_limits) {
        const limits = object(p.rate_limits);
        const windows = [limits.primary,limits.secondary].map(object).filter(window=>number(window.window_minutes)!==null)
          .map(window=>({...window,window_kind:window.window_minutes===300?'five_hour':window.window_minutes===10080?'weekly':'other'}));
        emit('ui.state','harness',null,{state_kind:'rate_limits',snapshot:p.rate_limits,windows},`limits:${row.record_uid}`);
      }
    } else if (subtype==='item_completed') {
      const item = object(p.item), itemType = string(item.type) ?? '', id = string(item.id) ?? row.record_uid;
      const ended = (number(p.completed_at_ms)??0)>0?number(p.completed_at_ms):null, started=(number(p.started_at_ms)??0)>0?number(p.started_at_ms):null;
      if (itemType==='UserMessage' || itemType==='AgentMessage') message(itemType==='UserMessage'?'user':'assistant',content(item.content),id,string(item.phase),40,false,contentChars(item.content));
      else if (itemType==='Reasoning') emit('reasoning','assistant',array(item.summary_text).filter(v=>typeof v==='string').join('\n') || array(item.raw_content).join('\n'),
        {encrypted:false,summary:array(item.summary_text),format:array(item.summary_text).length?'summary':'text'},`reasoning:${id}`,40,id);
      else if (itemType==='ContextCompaction') emit('context.compaction','harness',null,{},`compaction:${id}`);
      else if (itemType==='HookPrompt') emit('hook.run','hook',null,{fragments:array(item.fragments)},`hook:${id}`);
      else if (itemType==='Plan') emit('plan.update','assistant',null,{plan:item.plan ?? item},`plan:${id}`);
      else if (itemType==='SubAgentActivity') {
        const child = string(item.agent_thread_id);
        const kind=child&&item.kind==='started'?'subagent.spawn':child&&item.kind==='completed'?'subagent.result':'subagent.activity';
        emit(kind,'subagent',null,kind==='subagent.result'?{child_id:child,status:'completed'}:
          nonNull({child_id:child,agent_path:string(item.agent_path),metadata:item}),`subagent:${id}:${string(item.kind)}`,40,id);
      } else {
        let name = itemType, args: Json = item.arguments ?? item, output: Json | undefined = undefined, extra: Obj = {};
        if (itemType==='CommandExecution') {
          name='exec_command'; args={command:item.command ?? [],cwd:pathValue(item.cwd)};
          output=item.aggregated_output ?? item.formatted_output ?? item.stdout ?? item.stderr;
          const command = array(item.command);
          const parsed = array(item.parsed_cmd).map(object).find(v=>typeof v.cmd==='string');
          // command_head is the effective program (vocabulary key); the whole line stays in command_line.
          extra=nonNull({command,cwd:pathValue(item.cwd),command_head:commandHead(command)??commandHead(string(parsed?.cmd)),
            command_line:string(parsed?.cmd) ?? (command.length?command.map(String).join(' '):null)});
        } else if (itemType==='McpToolCall') {
          name=`mcp__${string(item.server) ?? 'unknown'}__${string(item.tool) ?? 'unknown'}`; output=item.result ?? item.error;
          extra=nonNull({mcp_server:string(item.server),mcp_tool:string(item.tool),is_error:Boolean(item.error)||Boolean(object(item.result).isError)});
        } else if (itemType==='FileChange') {
          name='apply_patch'; args=item.changes ?? {}; output=item.stdout ?? item.stderr;
          extra={files:Object.keys(object(item.changes))};
          emit('file.change','assistant',null,nonNull({changes:item.changes,status:string(item.status)}),`files:${id}`,40,id);
        } else if (itemType==='CollabAgentToolCall') { name=string(item.tool) ?? itemType; output=item.agents_states ?? null; }
        else if (itemType==='ImageView') { name='view_image'; args={path:pathValue(item.path)}; }
        else if (itemType==='Extension') { name=string(item.kind) ?? itemType; output=item.result ?? item.output; }
        else if (itemType==='WebSearch') { name='web.search'; output=item.results; }
        else if (itemType==='FunctionCallOutput') {
          emit('tool.result','tool',typeof item.output==='string'?item.output:content(item.output),{name:string(item.name)??'unknown',status:'unknown',...nonNull({output:structured(item.output??null)})},stableJson(['tool',turn,id,'result']),40,id,id); return result;
        } else if (itemType==='DynamicToolCall') { name=string(item.tool)??itemType; output=item.content_items ?? item.error; extra={is_error:item.success===false}; }
        else if (!['ImageGeneration','EnteredReviewMode','ExitedReviewMode'].includes(itemType)) { emit('unknown','harness',null,{native_type:row.native_type}); return result; }
        const wrappers=ctx.wrapperByTurn.get(turn ?? '') ?? [];
        if (id.startsWith('exec-')) {
          const wrapper=wrappers.filter(v=>v.ordinal<=row.ordinal).at(-1);
          if (wrapper) extra.parent_wrapper_id=wrapper.id;
        }
        const reportedDuration=durationMs(item.duration),bounds=started!==null&&ended!==null&&ended>=started?ended-started:null;
        tool(id,name,args,output,item.status,number(item.exit_code),reportedDuration??bounds,extra,40,started,ended,reportedDuration!==null?'reported':bounds!==null?'native_bounds':'unknown');
      }
    } else if (subtype==='thread_settings_applied') {
      emit('setting.change','harness',null,nonNull({model:string(object(p.thread_settings).model),effort:string(object(p.thread_settings).reasoning_effort),cwd:pathValue(object(p.thread_settings).cwd),settings:object(p.thread_settings)}));
    } else if (subtype==='thread_rolled_back') emit('branch','harness',null,nonNull({num_turns:number(p.num_turns)}));
    // Pre-item_completed Codex builds (protocol *_end events). Results pair with the function_call by call_id;
    // a later item_completed representation (priority 40) still wins over these (20).
    else if (subtype==='error' || subtype==='stream_error') emit('error','harness',string(p.message),nonNull({error:p.message??null,reason:subtype==='stream_error'?'stream_error':null}));
    else if (subtype==='exec_command_end' && string(p.call_id)) {
      const exit=number(p.exit_code),call=string(p.call_id)!,duration=durationMs(p.duration);
      const output=p.aggregated_output??p.formatted_output??p.stdout??p.stderr;
      emit('tool.result','tool',typeof output==='string'?output:null,nonNull({name:'exec_command',status:exit===null||exit===-1?status(p.status,exit):exit===0?'completed':'failed',
        exit_code:exit,duration_ms:duration,output:structured(output??null),duration_source:duration!==null?'reported':'unknown',duration_quality:duration!==null?'reported':'missing',status_scope:'command'}),
        stableJson(['tool',turn,call,'result']),20,call,call);
    } else if (subtype==='patch_apply_end' && string(p.call_id)) {
      const call=string(p.call_id)!;
      emit('tool.result','tool',string(p.stdout)??string(p.stderr),nonNull({name:'apply_patch',status:typeof p.success==='boolean'?(p.success?'completed':'failed'):'unknown',
        output:p.stdout??p.stderr??null,status_scope:'tool'}),stableJson(['tool',turn,call,'result']),20,call,call);
    } else if (subtype==='mcp_tool_call_end' && string(p.call_id)) {
      const call=string(p.call_id)!,invocation=object(p.invocation),result=object(p.result),duration=durationMs(p.duration);
      const failed='Err' in result||Boolean(object(result.Ok).isError);
      emit('tool.result','tool',content(object(result.Ok).content)||null,nonNull({name:`mcp__${string(invocation.server)??'unknown'}__${string(invocation.tool)??'unknown'}`,
        status:Object.keys(result).length?(failed?'failed':'completed'):'unknown',is_error:failed,duration_ms:duration,output:p.result??null,
        duration_source:duration!==null?'reported':'unknown',duration_quality:duration!==null?'reported':'missing',status_scope:'tool'}),stableJson(['tool',turn,call,'result']),20,call,call);
    }
    else if (subtype==='context_compacted') emit('context.compaction','harness',null,{});
    else emit('unknown','harness',null,{native_type:row.native_type});
  } else if (type==='inter_agent_communication_metadata') emit('context.inject','harness',null,{origin:'peer',context_type:'peer_metadata',context:p});
  else if (type==='inter_agent_communication') emit('message.user','subagent',content(p.content),{origin:'peer'});
  else if (type==='ghost_snapshot') return result;
  else emit('unknown','harness',null,{native_type:row.native_type});
  return result;
}

function rebuildSession(store: ConnectorStore, source: string, session: string): void {
  const native=session.split(':').slice(2).join(':');
  let meta: Obj={}, index: Obj={}, imported: Obj={}, edge: Obj={};
  const ctx: Context={source,session,native,kind:'main',meta,uiIds:new Set(),uiMessages:new Map(),exactByTurn:new Map(),fileMeta:new Map(),settings:new Map(),wrapperByTurn:new Map(),recordSettings:new Map(),legacyRequestByRecord:new Map(),snapshotByRecord:new Map(),hasExactUsage:false,snapshotCycleByRecord:new Map()};
  const currentSettings=new Map<string,Obj>();
  const latestResponse=new Map<string,string>();
  const usedLegacy=new Set<string>();
  let lastSnapshot:string|null=null,snapshotIdentity:string|null=null,previousTotal:Obj|null=null,cycle=0;
  const titleRows: RawRecord[]=[];
  for(const row of store.records(session)){
    const body=bodyOf(row),p=object(body.payload);
    if(body.type==='session_meta'&&p.id===native)ctx.fileMeta.set(row.file_id,p);
    if(body.type==='state_index')index=p;
  }
  const history=activeHistory(store,source,ctx.fileMeta,index);
  const inChain=(row:RawRecord)=>!history||!ctx.fileMeta.has(row.file_id)||(history.has(row.file_id)&&row.ordinal<history.get(row.file_id)!);
  const rolled=legacyRollbackRows(store,session,inChain);
  const inHistory=(row:RawRecord)=>inChain(row)&&!rolled.has(row.record_uid);
  for (const row of store.records(session)) {
    if(!inHistory(row))continue;
    const body=bodyOf(row), p=object(body.payload), type=string(body.type);
    if (type==='session_meta' && p.id===native) {
      meta={...meta,...p}; ctx.fileMeta.set(row.file_id,p);
      currentSettings.set(row.file_id,nonNull({cwd:string(p.cwd),model_provider_id:string(p.model_provider)}));
    }
    else if (type==='state_index') index=p;
    else if (type==='import_ledger') imported=p;
    else if (type==='spawn_edge') edge=p;
    if (type==='title_index') titleRows.push(row);
    if (type==='turn_context' || (type==='event_msg'&&p.type==='thread_settings_applied')) {
      const updated={...(currentSettings.get(row.file_id)??{}),...(type==='turn_context'?p:object(p.thread_settings))};
      if (type==='event_msg') updated.effort=object(p.thread_settings).reasoning_effort??updated.effort??null;
      currentSettings.set(row.file_id,updated);
      ctx.settings.set(`${row.file_id}:${row.turn_native_id}`,updated); ctx.settings.set(row.turn_native_id ?? '',updated);
    }
    ctx.recordSettings.set(row.record_uid,currentSettings.get(row.file_id)??{});
    if (type==='event_msg' && ['task_started','turn_started'].includes(String(p.type))) latestResponse.delete(row.file_id);
    if (type==='response_item' && (p.role==='assistant'||['reasoning','function_call','custom_tool_call'].includes(String(p.type)))) {
      const responseItem=string(p.id)??string(p.call_id); if (responseItem) latestResponse.set(row.file_id,responseItem);
    }
    if (type==='event_msg' && p.type==='token_count') {
      const info=object(p.info),totalUsage=object(info.total_token_usage);
      if (Object.keys(totalUsage).length && !syntheticTotal(info)) {
        // A fall in any reported running counter means the native total restarted.
        const fell=previousTotal!==null&&['input_tokens','output_tokens','total_tokens'].some(field=>{
          const before=number(previousTotal![field]),after=number(totalUsage[field]);return before!==null&&after!==null&&after<before;});
        if (fell) cycle++;
        ctx.snapshotCycleByRecord.set(row.record_uid,{cycle,reset:fell});previousTotal=totalUsage;
      }
      const identity=latestResponse.get(row.file_id);
      const total=stableJson(object(object(p.info).total_token_usage));
      // A repeated running total is a re-emission (no new request was billed): it must not become a call.
      if (identity && total!==lastSnapshot && !usedLegacy.has(`${identity}:${total}`)) {ctx.legacyRequestByRecord.set(row.record_uid,identity);usedLegacy.add(`${identity}:${total}`);}
      if (lastSnapshot!==total) {snapshotIdentity=`snapshot:${row.record_uid}`;lastSnapshot=total;}
      if (snapshotIdentity) ctx.snapshotByRecord.set(row.record_uid,snapshotIdentity);
    }
    if (type==='token_usage_record') ctx.hasExactUsage=true;
    if (type==='token_usage_record') ctx.exactByTurn.set(row.turn_native_id ?? '',`usage:${string(p.response_id) ?? row.record_uid}`);
    if (type==='event_msg' && p.type==='item_completed') {
      const item=object(p.item), id=string(item.id);
      if (id) ctx.uiIds.add(id);
      if (item.type==='UserMessage' || item.type==='AgentMessage') ctx.uiMessages.set(messageKey(item.type==='UserMessage'?'user':'assistant',row.turn_native_id,string(item.phase),content(item.content)),stableJson(['message','native',id ?? row.record_uid]));
    }
    if (type==='event_msg' && (p.type==='user_message'||p.type==='agent_message')) {
      const key=messageKey(p.type==='user_message'?'user':'assistant',row.turn_native_id,string(p.phase),string(p.message)??content(p.content));
      ctx.uiMessages.set(key,string(p.id)?stableJson(['message','native',string(p.id)]):stableJson(['message','legacy',ctx.session,row.sha256]));
    }
    if (type==='response_item' && p.type==='custom_tool_call' && p.name==='exec') {
      const wrappers=ctx.wrapperByTurn.get(row.turn_native_id ?? '') ?? [];
      wrappers.push({ordinal:row.ordinal,id:string(p.call_id)??row.record_uid}); ctx.wrapperByTurn.set(row.turn_native_id ?? '',wrappers);
    }
  }
  ctx.meta=meta; ctx.kind=classify(meta,index,Object.keys(imported).length>0);
  const subagent=object(object(meta.source).subagent), spawn=object(subagent.thread_spawn);
  const parent=string(meta.parent_thread_id) ?? string(spawn.parent_thread_id) ?? string(edge.parent_thread_id);
  const parentUid=parent?sessionUid(source,parent):null;
  const parentSession=parentUid?store.db.prepare('SELECT root_uid,depth FROM session WHERE session_uid=?').get(parentUid):null;
  const root=string(meta.session_id);
  const rootUid=root && root!==native?sessionUid(source,root):string(parentSession?.root_uid)??parentUid??session;
  const latestSettings=[...ctx.settings.values()].at(-1) ?? {};
  const cwd=pathValue(latestSettings.cwd) ?? pathValue(index.cwd) ?? pathValue(meta.cwd);
  const git=object(meta.git);
  const project=projectFor(store,cwd,string(index.git_origin_url)??string(git.repository_url));
  const titleIndex=titleRows.at(-1); const titlePayload=titleIndex?object(bodyOf(titleIndex).payload):{};
  const title=string(index.name) ?? string(titlePayload.thread_name) ?? string(titlePayload.name) ?? string(titlePayload.title) ?? string(index.title) ?? string(index.preview);
  const titleSource=index.name?'threads.name':titleIndex?'session_index':index.title?'threads.title':index.preview?'threads.preview':null;
  store.db.prepare(`INSERT INTO session(session_uid,source_id,native_id,kind,parent_uid,root_uid,depth,forked_from,imported_from,project_id,cwd,
    git_branch,git_sha,client,harness_version,title,title_source,started_at,ended_at,status,timezone,model_raw,effort_raw,metadata)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(session_uid) DO UPDATE SET kind=excluded.kind,parent_uid=excluded.parent_uid,root_uid=excluded.root_uid,
    depth=excluded.depth,forked_from=excluded.forked_from,imported_from=excluded.imported_from,project_id=excluded.project_id,
    cwd=excluded.cwd,git_branch=excluded.git_branch,git_sha=excluded.git_sha,client=excluded.client,harness_version=excluded.harness_version,
    title=excluded.title,title_source=excluded.title_source,started_at=COALESCE(excluded.started_at,session.started_at),timezone=excluded.timezone,model_raw=excluded.model_raw,effort_raw=excluded.effort_raw,metadata=excluded.metadata`).run(
      session,source,native,ctx.kind,parentUid,rootUid,number(spawn.depth)??(parent?Number(parentSession?.depth??0)+1:0),string(meta.forked_from_id),null,project,cwd,
      string(index.git_branch)??string(git.branch),string(index.git_sha)??string(git.commit_hash),string(meta.originator)??string(index.originator)??string(meta.source),
      string(meta.cli_version)??string(index.cli_version),title,titleSource,timestamp(meta.timestamp)??number(index.created_at_ms)??(number(index.created_at)===null?null:number(index.created_at)!*1000),null,'unknown',string(latestSettings.timezone),
      string(latestSettings.model)??string(index.model),string(latestSettings.effort)??string(index.reasoning_effort),JSON.stringify({meta,index,imported}));
  store.db.prepare('UPDATE session SET timezone_source=?,lineage_unresolved=? WHERE session_uid=?')
    .run(string(latestSettings.timezone)?'reported':'unknown',parentUid&&!parentSession?1:0,session);
  const winners=new Map<string,Candidate>(), mapped=new Map<string,Candidate[]>(), replayed: RawRecord[]=[], duplicates: {row:RawRecord,key:string}[]=[];
  const legacyCutoffs=new Map<string,number>();
  if (ctx.kind==='subagent' && parentUid) {
    const parentTurns=new Set(store.db.prepare('SELECT DISTINCT turn_native_id FROM current_record WHERE session_uid=?').all(parentUid).map(row=>row.turn_native_id));
    for (const row of store.records(session)) {
      const body=bodyOf(row), p=object(body.payload), fileMeta=ctx.fileMeta.get(row.file_id)??meta;
      if (!object(object(fileMeta.source).subagent).thread_spawn || number(fileMeta.subagent_history_start_ordinal)!==null || legacyCutoffs.has(row.file_id)) continue;
      if ((body.type==='inter_agent_communication_metadata'&&p.trigger_turn===true) ||
        (body.type==='event_msg'&&p.type==='item_completed'&&p.thread_id===native) ||
        (body.type==='event_msg'&&['task_started','turn_started'].includes(String(p.type))&&row.turn_native_id&&!parentTurns.has(row.turn_native_id))) legacyCutoffs.set(row.file_id,row.ordinal);
    }
  }
  const note=(row:RawRecord,disposition:Disposition,ref: string|null,reason:string|null) => store.db.prepare('UPDATE raw_record SET disposition=?,ref_event_uid=?,note=? WHERE record_uid=?').run(disposition,ref,reason,row.record_uid);
  for (const row of store.records(session)) {
    if(!inHistory(row)){note(row,'ignored',null,'reverted_history:outside_active_chain');continue;}
    if (!row.body || ['invalid_json_or_shape','oversized_line','invalid_ordinal','missing_session_meta'].includes(row.note??'')) continue;
    const body=bodyOf(row), p=object(body.payload), fileMeta=ctx.fileMeta.get(row.file_id) ?? meta;
    const spawnFile=object(object(fileMeta.source).subagent).thread_spawn;
    const cutoff=number(fileMeta.subagent_history_start_ordinal) ?? legacyCutoffs.get(row.file_id) ?? null;
    const forkCutoff=number(fileMeta.forked_from_ordinal_exclusive);
    const inherited=(body.type==='session_meta' && p.id!==native) || (body.type!=='session_meta' && ctx.kind!=='review' && ((spawnFile && cutoff!==null && row.ordinal<cutoff)
      || (!spawnFile && forkCutoff!==null && !fileMeta.history_base && row.ordinal<forkCutoff)));
    if (inherited) { replayed.push(row); continue; }
    const candidates=mapRecord(row,ctx);
    if (!candidates.length) { note(row,'ignored',null,'non_analytic_native_record'); continue; }
    mapped.set(row.record_uid,candidates);
    for (const candidate of candidates) {
      if (candidate.event.kind==='model.usage' && candidate.event.attrs.usage_scope==='call' && candidate.event.attrs.accounting==='legacy' && ctx.exactByTurn.has(row.turn_native_id??'')) {
        duplicates.push({row,key:ctx.exactByTurn.get(row.turn_native_id??'')!}); continue;
      }
      const old=winners.get(candidate.key);
      if (!old || candidate.priority>old.priority) {
        if (old) {
          candidate.position=Math.min(old.position,candidate.position);
          if (candidate.event.kind==='tool.call') {
            candidate.event.attrs.arguments=old.event.attrs.arguments??candidate.event.attrs.arguments??null;
            candidate.event.attrs.argument_digest=old.event.attrs.argument_digest??candidate.event.attrs.argument_digest??null;
            candidate.event.attrs.argument_digest_scope=old.event.attrs.argument_digest_scope??candidate.event.attrs.argument_digest_scope??'unavailable';
            if (old.event.attrs.input) candidate.event.attrs.input=old.event.attrs.input;
          }
        }
        winners.set(candidate.key,candidate);
      }
    }
  }
  clearProjection(store,session);
  const events=[...winners.values()].sort((a,b)=>a.position-b.position||a.slot-b.slot||a.record.file_id.localeCompare(b.record.file_id));
  for (const wrapper of events.filter(candidate=>candidate.event.kind==='tool.call'&&candidate.event.attrs.is_wrapper)) {
    const id=wrapper.event.call_id;
    const nested=events.filter(candidate=>candidate.event.kind==='tool.call'&&candidate.event.attrs.parent_wrapper_id===id&&candidate.event.turn_uid===wrapper.event.turn_uid&&candidate.event.attrs.category==='shell');
    const results=nested.map(call=>events.find(candidate=>candidate.event.kind==='tool.result'&&candidate.event.call_id===call.event.call_id&&candidate.event.turn_uid===call.event.turn_uid)?.event);
    const output=events.find(candidate=>candidate.event.kind==='tool.result'&&candidate.event.call_id===id&&candidate.event.turn_uid===wrapper.event.turn_uid)?.event;
    if (output) Object.assign(output.attrs,{status_scope:'outer_script',known_command_results:results.filter(event=>event&&['completed','failed'].includes(String(event.attrs.status))).length,
      failed_command_results:results.filter(event=>event?.attrs.status==='failed').length,unknown_return_values:null});
  }
  events.forEach((candidate,sequence)=>{
    candidate.event.seq=sequence; validateEvent(candidate.event); store.event(candidate.event);
    const context=ctx.recordSettings.get(candidate.record.record_uid)??{};
    const eventCwd=pathValue(candidate.event.attrs.cwd)??pathValue(context.cwd)??pathValue(meta.cwd)??pathValue(index.cwd);
    store.db.prepare('INSERT INTO event_context VALUES(?,?,?,?,?,?)').run(candidate.event.event_uid,projectFor(store,eventCwd,string(index.git_origin_url)??string(git.repository_url)),eventCwd,
      string(context.model_provider_id)??string(meta.model_provider),string(context.model),string(context.effort)??string(context.reasoning_effort));
    if (candidate.event.kind==='unknown') store.diagnostic(source,'unknown_type',`Unrecognized native type: ${candidate.record.native_type}`,candidate.record.file_id,candidate.record.record_uid);
  });
  for (const [record,candidates] of mapped) {
    const won=candidates.find(candidate=>winners.get(candidate.key)===candidate);
    const first=candidates[0]!;
    const ref=won?.event.event_uid ?? winners.get(first.key)?.event.event_uid ?? null;
    const usageDuplicate=duplicates.find(duplicate=>duplicate.row.record_uid===record);
    note(first.record,won?'mapped':'duplicate',ref ?? (usageDuplicate?winners.get(usageDuplicate.key)?.event.event_uid??null:null),won?null:'alternate_representation');
    for (const candidate of candidates) {
      const target=winners.get(candidate.key)??(candidate.event.attrs.accounting==='legacy'?winners.get(ctx.exactByTurn.get(candidate.record.turn_native_id??'')??''):undefined);
      if (target) store.db.prepare('INSERT OR IGNORE INTO record_event VALUES(?,?,?)').run(record,target.event.event_uid,winners.get(candidate.key)===candidate?'mapped':'duplicate');
    }
  }
  for (const row of replayed) {
    const p=object(bodyOf(row).payload), item=object(p.item), id=string(item.id)??string(p.id)??string(p.call_id);
    let original=parentUid && id ? store.db.prepare('SELECT event_uid FROM event WHERE session_uid=? AND native_id=? LIMIT 1').get(parentUid,id) : null;
    if (!original && parentUid && row.turn_native_id) original=store.db.prepare('SELECT event_uid FROM event WHERE session_uid=? AND turn_uid=? ORDER BY seq LIMIT 1')
      .get(parentUid,uid(parentUid,'turn',row.turn_native_id));
    note(row,'replayed',original?String(original.event_uid):null,original?'inherited_history':'inherited_history:parent_event_unavailable');
    if (original) store.db.prepare('INSERT OR IGNORE INTO record_event VALUES(?,?,?)').run(row.record_uid,String(original.event_uid),'replayed');
  }
  derive(store,ctx,events.map(candidate=>candidate.event));
  store.db.prepare('DELETE FROM dirty_session WHERE session_uid=?').run(session);
}

function derive(store: ConnectorStore, ctx: Context, events: StandardEvent[]): void {
  const turns=new Map<string,StandardEvent[]>(), tools=new Map<string,{call?:StandardEvent,result?:StandardEvent}>();
  for (const event of events) {
    if (event.turn_uid) { const values=turns.get(event.turn_uid)??[]; values.push(event); turns.set(event.turn_uid,values); }
    if (event.call_id && ['tool.call','tool.result'].includes(event.kind)) {
      const key=stableJson([event.turn_uid,event.call_id]), values=tools.get(key)??{};
      if (event.kind==='tool.call') values.call=event; else values.result=event;
      tools.set(key,values);
    }
    if (event.kind==='link') store.db.prepare('INSERT INTO link VALUES(?,?,?,?,?,?,?)').run(uid(event.event_uid,'link'),ctx.session,event.turn_uid,event.event_uid,string(event.attrs.kind),string(event.attrs.ref),event.ts);
    if (event.kind==='model.usage' && event.attrs.usage_scope!=='call') {
      const a=event.attrs;
      store.db.prepare(`INSERT INTO usage_snapshot(snapshot_uid,event_uid,session_uid,turn_uid,snapshot_key,usage_scope,measurement,coverage,provider,model_raw,effort_raw,purpose,
        observation_seq,ts,input_tokens,cache_read_tokens,cache_write_tokens,output_tokens,reasoning_tokens,reported,counter_cycle) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(event.event_uid,event.event_uid,ctx.session,event.turn_uid,
        string(a.snapshot_key),string(a.usage_scope),'cumulative',string(a.coverage),string(a.provider),string(a.model_raw),string(a.effort_raw),string(a.purpose),event.seq,event.ts,
        number(a.input_tokens),number(a.cache_read_tokens),number(a.cache_write_tokens),number(a.output_tokens),number(a.reasoning_tokens),JSON.stringify(a.reported),string(a.counter_cycle));
    }
    if (event.kind==='model.usage' && event.attrs.usage_scope==='call' && event.attrs.measurement==='delta') {
      const a=event.attrs;
      const model=string(a.model), effort=string(a.effort);
      const rank=effort?['none','minimal','low','medium','high','xhigh','max','ultra'].indexOf(effort):-1;
      store.db.prepare(`INSERT INTO model_call(call_uid,session_uid,turn_uid,request_id,provider,model_raw,model_id,effort_raw,effort_rank,purpose,
        input_tokens,cache_read_tokens,cache_write_tokens,output_tokens,reasoning_tokens,cost_usd,cost_source,latency_ms,ttft_ms,ts,estimated)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
        event.event_uid,ctx.session,event.turn_uid,string(a.request_id),string(a.provider),model,model,effort,rank<0?null:rank,
        ctx.kind==='review'?'review':ctx.kind==='subagent'?'subagent':ctx.kind==='auxiliary'?'auxiliary':'main',
        number(a.input_tokens),number(a.cache_read_tokens),number(a.cache_write_tokens),number(a.output_tokens),number(a.reasoning_tokens),null,'unknown',null,null,event.ts,a.estimated?1:0);
      store.db.prepare('UPDATE model_call SET usage_scope=?,measurement=?,coverage=?,request_key=?,usage_event_uid=? WHERE call_uid=?')
        .run('call','delta',string(a.coverage),JSON.stringify(a.request_key),event.event_uid,event.event_uid);
    }
  }
  let index=0;
  for (const [turn,values] of turns) {
    const start=values.find(event=>event.kind==='turn.start'), end=values.findLast(event=>event.kind==='turn.end');
    const startTime=object(start?.attrs.time);
    const duration=number(end?.attrs.duration_ms),ttft=number(end?.attrs.ttft_ms);
    store.db.prepare('INSERT INTO turn(turn_uid,session_uid,idx,trigger,status,started_at,ended_at,first_event_uid,last_event_uid,duration_ms,ttft_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?)')
      .run(turn,ctx.session,index++,string(start?.attrs.trigger)??'unknown',string(end?.attrs.status)??'unknown',
      startTime.semantics==='started'?start?.ts??null:null,object(end?.attrs.time).semantics==='completed'?end?.ts??null:null,values[0]!.event_uid,values.at(-1)!.event_uid,
      duration===null?null:Math.round(duration),ttft===null?null:Math.round(ttft));
    // Codex reports timing per turn, not per request. Requests inside a turn are sequential, so the turn's
    // first token comes from its first request: that call gets the turn TTFT. Wall latency is only
    // attributable when the turn is exactly one request and no tool ran; otherwise latency_ms stays NULL.
    const calls=values.filter(event=>event.kind==='model.usage'&&event.attrs.usage_scope==='call'&&event.attrs.measurement==='delta');
    if (calls.length && ttft!==null) store.db.prepare('UPDATE model_call SET ttft_ms=? WHERE call_uid=?').run(Math.round(ttft),calls[0]!.event_uid);
    if (calls.length===1 && duration!==null && !values.some(event=>event.kind==='tool.call'))
      store.db.prepare('UPDATE model_call SET latency_ms=? WHERE call_uid=?').run(Math.round(duration),calls[0]!.event_uid);
  }
  for (const [key,values] of tools) {
    const call=values.call,result=values.result,a=call?.attrs??{},r=result?.attrs??{};
    // A result without its call (call outside the retained history) is still categorized by name.
    const kind=string(a.category)??toolCategory(string(r.name)??'unknown');
    store.db.prepare(`INSERT INTO tool_call(call_uid,session_uid,turn_uid,call_event_uid,result_event_uid,name_raw,kind,mcp_server,mcp_tool,command_head,
      files,status,exit_code,started_at,ended_at,duration_ms,approval,is_wrapper,attribution) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      uid(ctx.session,key),ctx.session,call?.turn_uid??result?.turn_uid??null,call?.event_uid??null,result?.event_uid??null,
      string(a.name)??string(r.name)??'unknown',kind,string(a.mcp_server),string(a.mcp_tool),string(a.command_head),JSON.stringify(a.files??[]),
      string(r.status)??'unknown',number(r.exit_code),object(call?.attrs.time).semantics==='started'?call?.ts??null:null,number(r.ended_at),number(r.duration_ms),r.status==='declined'?'denied':null,a.is_wrapper?1:0,JSON.stringify(a.attribution??{}));
    store.db.prepare('UPDATE tool_call SET duration_source=?,duration_quality=?,status_scope=?,argument_digest=? WHERE call_uid=?')
      .run(string(r.duration_source)??'unknown',string(r.duration_quality)??'missing',string(r.status_scope)??(a.is_wrapper?'outer_script':'unknown'),string(a.argument_digest),uid(ctx.session,key));
    if (!a.is_wrapper && kind==='other') store.diagnostic(ctx.source,'unknown_tool_name',`Unclassified tool name: ${string(a.name)??string(r.name)??'unknown'}`);
    if (!a.is_wrapper) {
      for (const [feature,value] of [['tool_kind',kind],['command',string(a.command_head)],['mcp_server',string(a.mcp_server)]] as const) {
        if (value) store.db.prepare('INSERT INTO session_feature VALUES(?,?,?,1) ON CONFLICT(session_uid,feature,value) DO UPDATE SET n=n+1').run(ctx.session,feature,value);
      }
    }
  }
  const status=turns.size ? [...turns.values()].at(-1)?.findLast(event=>event.kind==='turn.end')?.attrs.status??'active' : 'unknown';
  store.db.prepare('UPDATE session SET started_at=COALESCE(started_at,?),ended_at=?,status=? WHERE session_uid=?')
    .run(events.find(event=>event.ts!==null)?.ts??null,events.findLast(event=>event.ts!==null)?.ts??null,String(status),ctx.session);
}

/**
 * Rebuild every dirty session of a source. A session whose mapping or validation throws is rolled back
 * on its own: it keeps its dirty marker (retried next run), gets a rebuild_failed diagnostic, and the
 * remaining sessions are still rebuilt. Failed session UIDs are appended to `failed` when given.
 */
export function rebuildSource(store: ConnectorStore, source: string, failed: string[] = []): number {
  const rows=store.db.prepare(`SELECT d.session_uid FROM dirty_session d WHERE EXISTS(SELECT 1 FROM current_record r
    JOIN source_file f USING(file_id) WHERE r.session_uid=d.session_uid AND f.source_id=?) OR EXISTS(SELECT 1 FROM session s WHERE s.session_uid=d.session_uid AND s.source_id=?)`).all(source,source);
  const pending=new Set(rows.map(row=>String(row.session_uid))), visited=new Set<string>(), visiting=new Set<string>(), broken=new Set<string>();
  let expanded=true;
  while (expanded) {
    expanded=false;
    for (const child of store.db.prepare('SELECT session_uid,parent_uid FROM session WHERE source_id=?').all(source)) {
      if (child.parent_uid && pending.has(String(child.parent_uid))&&!pending.has(String(child.session_uid))) {pending.add(String(child.session_uid));expanded=true;}
    }
  }
  function rebuild(session:string):void {
    if (visited.has(session)) return;
    if (visiting.has(session)) { store.diagnostic(source,'lineage_cycle','Thread lineage contains a cycle'); return; }
    visiting.add(session);
    if(!store.db.prepare('SELECT 1 FROM current_record WHERE session_uid=? LIMIT 1').get(session)){
      store.transaction(()=>{clearProjection(store,session);store.db.prepare('DELETE FROM session WHERE session_uid=?').run(session);store.db.prepare('DELETE FROM dirty_session WHERE session_uid=?').run(session);});
      visited.add(session);visiting.delete(session);return;
    }
    for (const row of store.records(session)) {
      const body=bodyOf(row),p=object(body.payload);
      if (body.type==='session_meta' || body.type==='spawn_edge') {
        const parent=string(p.parent_thread_id)??string(object(object(object(p.source).subagent).thread_spawn).parent_thread_id);
        if (parent) { const parentUid=sessionUid(source,parent); if (pending.has(parentUid)) rebuild(parentUid); }
      }
    }
    try { store.transaction(()=>rebuildSession(store,source,session)); }
    catch (error) {
      broken.add(session); failed.push(session);
      const message=redact(error instanceof Error?error.message:String(error)).slice(0,2000);
      store.diagnostic(source,'rebuild_failed',`Session ${session} could not be rebuilt; its projection is unchanged and it stays dirty: ${message}`);
    }
    visited.add(session); visiting.delete(session);
  }
  for (const session of pending) rebuild(session);
  return visited.size-broken.size;
}
