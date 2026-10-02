import { watch } from 'node:fs';
import type { CodexConnector, IngestOptions } from './ingest.ts';
import type { IngestResult } from './types.ts';

export interface WatchOptions {
  signal: AbortSignal; debounceMs?: number; pollMs?: number;
  onResult: (result: IngestResult) => void; onError?: (error: unknown) => void;
  ingest?: IngestOptions;
}
/** Serialized ingests coalesce FSEvents notifications; periodic stat scans cover missed notifications. */
export async function watchCodex(connector: CodexConnector, options: WatchOptions): Promise<void> {
  if (options.signal.aborted) return;
  let pending=false, active:Promise<void>|null=null;
  let timer:ReturnType<typeof setTimeout>|null=null;
  const run=():void=>{
    pending=true;
    if (active) return;
    active=(async()=>{
      while (pending && !options.signal.aborted) {
        pending=false;
        try { options.onResult(await connector.ingest(options.ingest)); }
        catch(error) { options.onError?.(error); }
      }
    })().finally(()=>{active=null;});
  };
  const schedule=():void=>{
    if (timer) clearTimeout(timer);
    timer=setTimeout(run,options.debounceMs??1000);
  };
  let watcher:ReturnType<typeof watch>|null=null;
  let interval=setInterval(run,options.pollMs??600000);
  const fallback=(error:unknown):void=>{
    watcher?.close(); watcher=null; clearInterval(interval);
    interval=setInterval(run,options.pollMs??2000);
    options.onError?.(error);
  };
  try {
    watcher=watch(connector.root,{recursive:true},(_event,name)=>{
      if (name && /^(sessions|archived_sessions|state_\d+\.sqlite|session_index\.jsonl|external_agent_session_imports\.json|\.tmp\/rollout-maintenance\.lock)/.test(String(name))) schedule();
    });
    watcher.on('error',fallback);
  } catch(error) { fallback(error); }
  const stopped=new Promise<void>(resolve=>options.signal.addEventListener('abort',()=>resolve(),{once:true}));
  run();
  try { await stopped; }
  finally {
    watcher?.close(); clearInterval(interval); if (timer) clearTimeout(timer);
    await active;
  }
}
