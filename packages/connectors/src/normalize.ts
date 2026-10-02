import { object, string, number, array } from './types.ts';
import type { Obj, Json, RawRecord, StandardEvent, Disposition } from './types.ts';
import { uid, hash, sessionUid, timestamp, durationMs, pathValue, stableJson } from './util.ts';
import { validateEvent } from './contract.ts';
import { projectFor } from './project.ts';
import type { ConnectorStore } from './store.ts';

interface Candidate { event: StandardEvent; key: string; priority: number; record: RawRecord; }
interface Context {
  source: string; session: string; native: string; kind: string; meta: Obj;
  uiIds: Set<string>; uiMessages: Map<string,string>; exactByTurn: Map<string,string>;
  fileMeta: Map<string,Obj>; settings: Map<string,Obj>; wrapperByTurn: Map<string,{ordinal:number,id:string}[]>;
  recordSettings: Map<string,Obj>;
}
const nonNull = (value: Record<string,Json|undefined>): Obj => Object.fromEntries(Object.entries(value).filter(([,v])=>v!==null&&v!==undefined)) as Obj;
function bodyOf(row: RawRecord): Obj { return row.body ? object(JSON.parse(row.body)) : {}; }
function content(value: unknown): string {
  if (typeof value === 'string') return value;
  return array(value).map(item => string(object(item).text) ?? string(object(item).summary_text) ?? '').filter(Boolean).join('\n');
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
function toolCategory(name: string): string {
  if (/^mcp__/.test(name)) return 'mcp';
  if (/^(exec_command|local_shell|CommandExecution|bash|shell)$/.test(name)) return 'shell';
  if (/^(apply_patch|FileChange|edit_file)$/.test(name)) return 'file.edit';
  if (/^(view_image|ImageView|read_file)$/.test(name)) return 'file.read';
  if (/^(spawn_agent|send_message|send_input|followup_task|wait_agent|SubAgentActivity|CollabAgentToolCall)$/.test(name)) return 'subagent';
  if (/update_plan|TodoWrite/.test(name)) return 'plan';
  if (/request_user_input/.test(name)) return 'ask_user';
  if (/web.*search|WebSearch/.test(name)) return 'web.search';
  if (/web.*fetch|web.*open/.test(name)) return 'web.fetch';
  return 'other';
}
function status(value: unknown, exit: number | null = null, isError = false): string {
  if (isError || (exit !== null && exit !== 0 && exit !== -1)) return 'failed';
  const raw = string(value)?.replace('inProgress','in_progress');
  return raw && ['completed','failed','declined','interrupted','in_progress'].includes(raw) ? raw : 'unknown';
}
function usageAttrs(usage: Obj, settings: Obj, ctx: Context, request: string, accounting: string): Obj {
  const totalInput = number(usage.input_tokens) ?? 0, read = number(usage.cached_input_tokens) ?? 0, write = number(usage.cache_write_input_tokens) ?? 0;
  return nonNull({provider:string(settings.model_provider_id) ?? string(ctx.meta.model_provider) ?? 'openai',model:string(settings.model),
    effort:string(settings.effort) ?? string(settings.reasoning_effort),request_id:request,
    input_tokens:Math.max(0,totalInput-read-write),cache_read_tokens:read,cache_write_tokens:write,
    output_tokens:number(usage.output_tokens) ?? 0,reasoning_tokens:number(usage.reasoning_output_tokens) ?? 0,
    accounting,estimated:ctx.kind==='import',native_usage:usage});
}
function mapRecord(row: RawRecord, ctx: Context): Candidate[] {
  const body = bodyOf(row), p = object(body.payload), type = string(body.type) ?? '', subtype = string(p.type) ?? '';
  const result: Candidate[] = [];
  const turn = row.turn_native_id, settings = ctx.recordSettings.get(row.record_uid) ?? {};
  const defaultTime = row.ts ?? timestamp(ctx.meta.timestamp) ?? 0;
  function emit(kind: string, actor: string, text: string | null, attrs: Obj = {}, key = uid(row.record_uid,result.length), priority = 10,
    native: string | null = null, call: string | null = null, ts = defaultTime): void {
    result.push({key,priority,record:row,event:{event_uid:uid(ctx.source,ctx.session,key),session_uid:ctx.session,seq:0,ts,kind,actor,
      turn_uid:turn ? uid(ctx.session,'turn',turn) : null,parent_uid:null,call_id:call,text,text_truncated:text?.includes('<truncated:sha256:') ? 1 : 0,
      attrs,ext:{native:body},record_uid:row.record_uid,native_id:native}});
  }
  function message(role: string, text: string, id: string | null, phase: string | null, priority: number, isResponse = false): void {
    const signature = messageKey(role,turn,phase,text);
    const uiKey = ctx.uiMessages.get(signature) ?? ctx.uiMessages.get(messageKey(role,turn,null,text));
    const key = isResponse ? (id && ctx.uiIds.has(id) ? `message:${id}` : uiKey ?? (id ? `message:${id}` : `message:${signature}`))
      : id ? `message:${id}` : `message:legacy:${uid(ctx.session,row.sha256)}`;
    if (role === 'user' && isResponse && !uiKey) {
      emit('context.inject','harness',text,{origin:'injected',role},`injection:${row.record_uid}`); return;
    }
    emit(role==='user' ? 'message.user' : 'message.assistant',role==='user' && origin(ctx)==='human' ? 'human' : role==='user' ? 'harness' : 'assistant',text,
      role==='user' ? {origin:origin(ctx)} : nonNull({phase}),key,priority,id);
  }
  function tool(id: string, name: string, argumentsValue: Json, output: Json | undefined, rawStatus: unknown,
    exit: number | null, duration: number | null, extra: Obj = {}, priority = 30, started: number | null = null, ended = defaultTime): void {
    const isError = Boolean(object(output).isError) || Boolean(extra.is_error);
    const state = status(rawStatus,exit,isError);
    const {is_error:_error,...callExtra}=extra;
    emit('tool.call','assistant',null,{name,category:toolCategory(name),arguments:argumentsValue,...callExtra},`tool:${turn}:${id}:call`,priority,id,id,started ?? defaultTime);
    if (output !== undefined || rawStatus !== undefined) emit('tool.result','tool',typeof output==='string' ? output : content(object(output).content) || null,
      nonNull({name,status:state,exit_code:exit,duration_ms:duration,started_at:started,ended_at:ended,is_error:isError,output:output}),`tool:${turn}:${id}:result`,priority,id,id,ended);
    if (state==='declined') emit('permission.decision','harness',null,{decision:'denied',source:'unavailable'},`permission:${turn}:${id}`,priority,id,id);
  }
  if (type === 'session_meta') {
    emit('session.meta','harness',null,nonNull({cwd:string(p.cwd),provider:string(p.model_provider),history_mode:string(p.history_mode),thread_source:string(p.thread_source),metadata:p}),`meta:${row.record_uid}`,10,string(p.id));
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
    emit('context.inject','harness',null,{origin:'world_state',context:p},`world:${row.record_uid}`);
  } else if (type === 'compacted') {
    emit('context.compaction','harness',string(p.message),nonNull({compaction_response_id:string(p.compaction_response_id),window_id:p.window_id,
      window_number:number(p.window_number),replacement_count:array(p.replacement_history).length}),`compaction:${string(p.compaction_response_id) ?? row.record_uid}`);
  } else if (type === 'token_usage_record') {
    const request = string(p.response_id) ?? row.record_uid;
    emit('model.usage','harness',null,usageAttrs(object(p.usage),settings,ctx,request,'exact'),`usage:${request}`,40,request);
  } else if (type === 'response_item') {
    const id = string(p.id), call = string(p.call_id) ?? id ?? row.record_uid;
    if (subtype === 'message') {
      const role = string(p.role);
      if (role==='user' || role==='assistant') message(role,content(p.content),id,string(p.phase),10,true);
      else emit('context.inject','harness',content(p.content),{origin:'injected',role:role ?? 'developer'},`injection:${row.record_uid}`);
    } else if (subtype === 'reasoning') {
      emit('reasoning','assistant',content(p.summary) || content(p.content),{encrypted:Boolean(p.encrypted_content),summary:array(p.summary)},id?`reasoning:${id}`:`reasoning:${row.record_uid}`,10,id);
    } else if (['function_call','custom_tool_call','local_shell_call','tool_search_call','web_search_call','image_generation_call'].includes(subtype)) {
      const name = string(p.name) ?? subtype;
      let args: Json = p.arguments ?? p.action ?? p.input ?? {};
      if (typeof args==='string' && subtype==='function_call') { try { args=JSON.parse(args) as Json; } catch { /* native string retained */ } }
      const wrapper = subtype==='custom_tool_call' && ['exec','wait'].includes(name);
      tool(call,name,args,undefined,undefined,null,null,nonNull({is_wrapper:wrapper,input:subtype==='custom_tool_call'?string(p.input):null,
        attribution:object(body.metadata),mcp_server:name.startsWith('mcp__')?name.split('__')[1]:null,mcp_tool:name.startsWith('mcp__')?name.split('__').slice(2).join('__'):null}),10);
    } else if (['function_call_output','custom_tool_call_output','tool_search_output'].includes(subtype)) {
      const name = string(p.name) ?? 'unknown';
      emit('tool.result','tool',typeof p.output==='string' ? p.output : content(p.output),{name,status:'unknown',output:p.output ?? p.tools ?? null},`tool:${turn}:${call}:result`,10,call,call);
    } else if (['compaction','compaction_summary','context_compaction'].includes(subtype)) {
      emit('context.compaction','harness',null,{},`compaction:${id ?? row.record_uid}`);
    } else if (subtype==='agent_message') {
      emit('message.user','subagent',content(p.content),{origin:'peer'},`peer:${id ?? row.record_uid}`,20,id);
    } else emit('unknown','harness',null,{native_type:row.native_type});
  } else if (type === 'event_msg') {
    if (['task_started','turn_started'].includes(subtype)) {
      emit('turn.start','harness',null,nonNull({trigger:ctx.kind==='automation'?'automation':ctx.kind==='subagent'?'peer':'human',
        started_at:number(p.started_at)===null?null:Math.round(number(p.started_at)!*1000),model_context_window:number(p.model_context_window)}),`turn:${turn}:start`,30,null,null,number(p.started_at)===null?defaultTime:Math.round(number(p.started_at)!*1000));
    } else if (['task_complete','turn_complete','turn_aborted'].includes(subtype)) {
      const state = p.error ? 'failed' : subtype==='turn_aborted' ? 'interrupted' : 'completed';
      emit('turn.end','harness',null,nonNull({status:state,duration_ms:number(p.duration_ms),ttft_ms:number(p.time_to_first_token_ms),error:p.error,reason:string(p.reason)}),`turn:${turn}:end`,30,null,null,
        number(p.completed_at)===null?defaultTime:Math.round(number(p.completed_at)!*1000));
      if (p.error) emit('error','harness',null,{error:p.error},`error:${row.record_uid}`);
    } else if (subtype==='user_message' || subtype==='agent_message') message(subtype==='user_message'?'user':'assistant',string(p.message) ?? content(p.content),string(p.id),string(p.phase),30);
    else if (subtype==='agent_reasoning' || subtype==='agent_reasoning_raw_content') emit('reasoning','assistant',string(p.text),{encrypted:false},`reasoning:${string(p.id) ?? row.record_uid}`,20,string(p.id));
    else if (subtype==='token_count') {
      const info = object(p.info), total = object(info.total_token_usage), last = object(info.last_token_usage);
      const synthetic = number(total.total_tokens)===number(info.model_context_window) && (number(total.input_tokens)??0)===0 && (number(total.output_tokens)??0)===0;
      if (Object.keys(last).length && !synthetic) emit('model.usage','harness',null,usageAttrs(last,settings,ctx,`legacy:${uid(total)}`,'legacy'),`legacy-usage:${uid(total)}`,10);
      if (p.rate_limits) {
        const limits = object(p.rate_limits);
        const windows = [limits.primary,limits.secondary].map(object).filter(window=>number(window.window_minutes)!==null)
          .map(window=>({...window,window_kind:window.window_minutes===300?'five_hour':window.window_minutes===10080?'weekly':'other'}));
        emit('ui.state','harness',null,{state_kind:'rate_limits',snapshot:p.rate_limits,windows},`limits:${row.record_uid}`);
      }
    } else if (subtype==='item_completed') {
      const item = object(p.item), itemType = string(item.type) ?? '', id = string(item.id) ?? row.record_uid;
      const ended = number(p.completed_at_ms) || defaultTime, started = number(p.started_at_ms);
      if (itemType==='UserMessage' || itemType==='AgentMessage') message(itemType==='UserMessage'?'user':'assistant',content(item.content),id,string(item.phase),40);
      else if (itemType==='Reasoning') emit('reasoning','assistant',array(item.summary_text).filter(v=>typeof v==='string').join('\n') || array(item.raw_content).join('\n'),
        {encrypted:false,summary:array(item.summary_text)},`reasoning:${id}`,40,id);
      else if (itemType==='ContextCompaction') emit('context.compaction','harness',null,{},`compaction:${id}`);
      else if (itemType==='HookPrompt') emit('hook.run','hook',null,{fragments:array(item.fragments)},`hook:${id}`);
      else if (itemType==='Plan') emit('plan.update','assistant',null,{plan:item.plan ?? item},`plan:${id}`);
      else if (itemType==='SubAgentActivity') {
        const child = string(item.agent_thread_id) ?? id;
        emit(item.kind==='completed'?'subagent.result':'subagent.spawn','subagent',null,item.kind==='completed'?{child_id:child,status:'completed'}:nonNull({child_id:child,agent_path:string(item.agent_path),metadata:item}),`subagent:${id}:${string(item.kind)}`,40,id);
      } else {
        let name = itemType, args: Json = item.arguments ?? item, output: Json | undefined = undefined, extra: Obj = {};
        if (itemType==='CommandExecution') {
          name='exec_command'; args={command:item.command ?? [],cwd:pathValue(item.cwd)};
          output=item.aggregated_output ?? item.formatted_output ?? item.stdout ?? item.stderr;
          const command = array(item.command);
          const parsed = array(item.parsed_cmd).map(object).find(v=>typeof v.cmd==='string');
          extra=nonNull({command,cwd:pathValue(item.cwd),command_head:string(parsed?.cmd) ?? command.map(String).join(' ')});
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
          emit('tool.result','tool',typeof item.output==='string'?item.output:content(item.output),{name:string(item.name)??'unknown',status:'unknown',output:item.output??null},`tool:${turn}:${id}:result`,40,id,id); return result;
        } else if (itemType==='DynamicToolCall') { name=string(item.tool)??itemType; output=item.content_items ?? item.error; extra={is_error:item.success===false}; }
        else if (!['ImageGeneration','EnteredReviewMode','ExitedReviewMode'].includes(itemType)) { emit('unknown','harness',null,{native_type:row.native_type}); return result; }
        const wrappers=ctx.wrapperByTurn.get(turn ?? '') ?? [];
        if (id.startsWith('exec-')) {
          const wrapper=wrappers.filter(v=>v.ordinal<=row.ordinal).at(-1);
          if (wrapper) extra.parent_wrapper_id=wrapper.id;
        }
        tool(id,name,args,output,item.status,number(item.exit_code),durationMs(item.duration) ?? (started===null?null:ended-started),extra,40,started,ended);
      }
    } else if (subtype==='thread_settings_applied') {
      emit('setting.change','harness',null,nonNull({model:string(object(p.thread_settings).model),effort:string(object(p.thread_settings).reasoning_effort),cwd:pathValue(object(p.thread_settings).cwd),settings:object(p.thread_settings)}));
    } else if (subtype==='thread_rolled_back') emit('branch','harness',null,nonNull({num_turns:number(p.num_turns)}));
    else if (subtype==='context_compacted') emit('context.compaction','harness',null,{});
    else emit('unknown','harness',null,{native_type:row.native_type});
  } else if (type==='inter_agent_communication_metadata') emit('context.inject','harness',null,{origin:'peer_metadata',context:p});
  else if (type==='inter_agent_communication') emit('message.user','subagent',content(p.content),{origin:'peer'});
  else if (type==='ghost_snapshot') return result;
  else emit('unknown','harness',null,{native_type:row.native_type});
  return result;
}

function rebuildSession(store: ConnectorStore, source: string, session: string): void {
  const native=session.split(':').slice(2).join(':');
  let meta: Obj={}, index: Obj={}, imported: Obj={}, edge: Obj={};
  const ctx: Context={source,session,native,kind:'main',meta,uiIds:new Set(),uiMessages:new Map(),exactByTurn:new Map(),fileMeta:new Map(),settings:new Map(),wrapperByTurn:new Map(),recordSettings:new Map()};
  const currentSettings=new Map<string,Obj>();
  const titleRows: RawRecord[]=[];
  for (const row of store.records(session)) {
    const body=bodyOf(row), p=object(body.payload), type=string(body.type);
    if (type==='session_meta' && p.id===native) { meta=p; ctx.fileMeta.set(row.file_id,p); }
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
    if (type==='token_usage_record') ctx.exactByTurn.set(row.turn_native_id ?? '',`usage:${string(p.response_id) ?? row.record_uid}`);
    if (type==='event_msg' && p.type==='item_completed') {
      const item=object(p.item), id=string(item.id);
      if (id) ctx.uiIds.add(id);
      if (item.type==='UserMessage' || item.type==='AgentMessage') ctx.uiMessages.set(messageKey(item.type==='UserMessage'?'user':'assistant',row.turn_native_id,string(item.phase),content(item.content)),`message:${id ?? row.record_uid}`);
    }
    if (type==='event_msg' && (p.type==='user_message'||p.type==='agent_message')) {
      const key=messageKey(p.type==='user_message'?'user':'assistant',row.turn_native_id,string(p.phase),string(p.message)??content(p.content));
      ctx.uiMessages.set(key,string(p.id)?`message:${string(p.id)}`:`message:legacy:${uid(ctx.session,row.sha256)}`);
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
  const root=string(meta.session_id) ?? parent ?? native;
  const latestSettings=[...ctx.settings.values()].at(-1) ?? {};
  const cwd=pathValue(latestSettings.cwd) ?? pathValue(index.cwd) ?? pathValue(meta.cwd);
  const git=object(meta.git);
  const project=projectFor(store,cwd,string(index.git_origin_url)??string(git.repository_url));
  const titleIndex=titleRows.at(-1); const titlePayload=titleIndex?object(bodyOf(titleIndex).payload):{};
  const title=string(index.name) ?? string(titlePayload.thread_name) ?? string(titlePayload.name) ?? string(titlePayload.title) ?? string(index.title) ?? string(index.preview);
  const titleSource=index.name?'threads.name':titleIndex?'session_index':index.title?'threads.title':index.preview?'threads.preview':null;
  store.db.prepare(`INSERT INTO session VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(session_uid) DO UPDATE SET kind=excluded.kind,parent_uid=excluded.parent_uid,root_uid=excluded.root_uid,
    depth=excluded.depth,forked_from=excluded.forked_from,imported_from=excluded.imported_from,project_id=excluded.project_id,
    cwd=excluded.cwd,git_branch=excluded.git_branch,git_sha=excluded.git_sha,client=excluded.client,harness_version=excluded.harness_version,
    title=excluded.title,title_source=excluded.title_source,timezone=excluded.timezone,model_raw=excluded.model_raw,effort_raw=excluded.effort_raw,metadata=excluded.metadata`).run(
      session,source,native,ctx.kind,parentUid,sessionUid(source,root),number(spawn.depth)??(parent?1:0),string(meta.forked_from_id),string(imported.source_path),project,cwd,
      string(index.git_branch)??string(git.branch),string(index.git_sha)??string(git.commit_hash),string(meta.originator)??string(index.originator)??string(meta.source),
      string(meta.cli_version)??string(index.cli_version),title,titleSource,timestamp(meta.timestamp),null,'unknown',string(latestSettings.timezone),
      string(latestSettings.model)??string(index.model),string(latestSettings.effort)??string(index.reasoning_effort),JSON.stringify({meta,index,imported}));
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
    if (!row.body || row.note==='invalid_json_or_shape' || row.note==='oversized_line') continue;
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
      if (candidate.event.kind==='model.usage' && candidate.event.attrs.accounting==='legacy' && ctx.exactByTurn.has(row.turn_native_id??'')) {
        duplicates.push({row,key:ctx.exactByTurn.get(row.turn_native_id??'')!}); continue;
      }
      const old=winners.get(candidate.key);
      if (!old || candidate.priority>old.priority) {
        if (old && candidate.event.kind==='tool.call') candidate.event.ts=Math.min(old.event.ts,candidate.event.ts);
        winners.set(candidate.key,candidate);
      }
    }
  }
  for (const table of ['event','turn','tool_call','model_call']) store.db.prepare(`DELETE FROM ${table} WHERE session_uid=?`).run(session);
  const events=[...winners.values()].sort((a,b)=>a.event.ts-b.event.ts||a.record.ordinal-b.record.ordinal||a.record.line_no-b.record.line_no);
  events.forEach((candidate,index)=>{
    candidate.event.seq=index; validateEvent(candidate.event); store.event(candidate.event);
    if (candidate.event.kind==='unknown') store.diagnostic(source,'unknown_type',`Unrecognized native type: ${candidate.record.native_type}`,candidate.record.file_id,candidate.record.record_uid);
  });
  for (const [record,candidates] of mapped) {
    const won=candidates.find(candidate=>winners.get(candidate.key)===candidate);
    const first=candidates[0]!;
    const ref=won?.event.event_uid ?? winners.get(first.key)?.event.event_uid ?? null;
    const usageDuplicate=duplicates.find(duplicate=>duplicate.row.record_uid===record);
    note(first.record,won?'mapped':'duplicate',ref ?? (usageDuplicate?winners.get(usageDuplicate.key)?.event.event_uid??null:null),won?null:'alternate_representation');
  }
  for (const row of replayed) {
    const p=object(bodyOf(row).payload), item=object(p.item), id=string(item.id)??string(p.id)??string(p.call_id);
    let original=parentUid && id ? store.db.prepare('SELECT event_uid FROM event WHERE session_uid=? AND native_id=? LIMIT 1').get(parentUid,id) : null;
    if (!original && parentUid && row.turn_native_id) original=store.db.prepare('SELECT event_uid FROM event WHERE session_uid=? AND turn_uid=? ORDER BY seq LIMIT 1')
      .get(parentUid,uid(parentUid,'turn',row.turn_native_id));
    note(row,'replayed',original?String(original.event_uid):null,original?'inherited_history':'inherited_history:parent_event_unavailable');
  }
  derive(store,ctx,events.map(candidate=>candidate.event));
  store.db.prepare('DELETE FROM dirty_session WHERE session_uid=?').run(session);
}

function derive(store: ConnectorStore, ctx: Context, events: StandardEvent[]): void {
  const turns=new Map<string,StandardEvent[]>(), tools=new Map<string,{call?:StandardEvent,result?:StandardEvent}>();
  for (const event of events) {
    if (event.turn_uid) { const values=turns.get(event.turn_uid)??[]; values.push(event); turns.set(event.turn_uid,values); }
    if (event.call_id && ['tool.call','tool.result'].includes(event.kind)) {
      const key=`${event.turn_uid}:${event.call_id}`, values=tools.get(key)??{};
      if (event.kind==='tool.call') values.call=event; else values.result=event;
      tools.set(key,values);
    }
    if (event.kind==='model.usage') {
      const a=event.attrs;
      const model=string(a.model), effort=string(a.effort);
      const rank=effort?['none','minimal','low','medium','high','xhigh','max','ultra'].indexOf(effort):-1;
      store.db.prepare('INSERT INTO model_call VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run(
        event.event_uid,ctx.session,event.turn_uid,string(a.request_id),string(a.provider),model,model,effort,rank<0?null:rank,
        ctx.kind==='review'?'review':ctx.kind==='subagent'?'subagent':ctx.kind==='auxiliary'?'auxiliary':'main',
        number(a.input_tokens),number(a.cache_read_tokens),number(a.cache_write_tokens),number(a.output_tokens),number(a.reasoning_tokens),null,'unknown',null,null,event.ts,a.estimated?1:0);
    }
  }
  let index=0;
  for (const [turn,values] of turns) {
    const start=values.find(event=>event.kind==='turn.start'), end=values.findLast(event=>event.kind==='turn.end');
    store.db.prepare('INSERT INTO turn VALUES(?,?,?,?,?,?,?,?,?)').run(turn,ctx.session,index++,string(start?.attrs.trigger)??'unknown',string(end?.attrs.status)??'incomplete',
      start?.ts??values[0]!.ts,end?.ts??null,values[0]!.event_uid,values.at(-1)!.event_uid);
  }
  for (const [key,values] of tools) {
    const call=values.call,result=values.result,a=call?.attrs??{},r=result?.attrs??{};
    store.db.prepare('INSERT INTO tool_call VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)').run(
      uid(ctx.session,key),ctx.session,call?.turn_uid??result?.turn_uid??null,call?.event_uid??null,result?.event_uid??null,
      string(a.name)??string(r.name)??'unknown',string(a.category)??'other',string(a.mcp_server),string(a.mcp_tool),string(a.command_head),JSON.stringify(a.files??[]),
      string(r.status)??'incomplete',number(r.exit_code),call?.ts??null,result?.ts??null,number(r.duration_ms),r.status==='declined'?'denied':null,a.is_wrapper?1:0,JSON.stringify(a.attribution??{}));
  }
  const status=turns.size ? [...turns.values()].at(-1)?.findLast(event=>event.kind==='turn.end')?.attrs.status??'active' : 'unknown';
  store.db.prepare('UPDATE session SET started_at=COALESCE(started_at,?),ended_at=?,status=? WHERE session_uid=?')
    .run(events[0]?.ts??null,events.at(-1)?.ts??null,String(status),ctx.session);
}

export function rebuildSource(store: ConnectorStore, source: string): number {
  const rows=store.db.prepare(`SELECT d.session_uid FROM dirty_session d WHERE EXISTS(SELECT 1 FROM current_record r
    JOIN source_file f USING(file_id) WHERE r.session_uid=d.session_uid AND f.source_id=?) OR EXISTS(SELECT 1 FROM session s WHERE s.session_uid=d.session_uid AND s.source_id=?)`).all(source,source);
  const pending=new Set(rows.map(row=>String(row.session_uid))), visited=new Set<string>(), visiting=new Set<string>();
  function rebuild(session:string):void {
    if (visited.has(session)) return;
    if (visiting.has(session)) { store.diagnostic(source,'lineage_cycle','Thread lineage contains a cycle'); return; }
    visiting.add(session);
    for (const row of store.records(session)) {
      const body=bodyOf(row),p=object(body.payload);
      if (body.type==='session_meta') {
        const parent=string(p.parent_thread_id)??string(object(object(object(p.source).subagent).thread_spawn).parent_thread_id);
        if (parent) { const parentUid=sessionUid(source,parent); if (pending.has(parentUid)) rebuild(parentUid); }
      }
    }
    store.transaction(()=>rebuildSession(store,source,session)); visited.add(session); visiting.delete(session);
  }
  for (const session of pending) rebuild(session);
  return visited.size;
}
