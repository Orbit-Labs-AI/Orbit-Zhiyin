import { readFile, stat } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { platform } from 'node:os';

export async function maintenanceState(path:string):Promise<'held'|'idle'|'unknown'> {
  let info;
  try {info=await stat(path,{bigint:true});} catch(error) {
    return (error as NodeJS.ErrnoException).code==='ENOENT'?'idle':'unknown';
  }
  // Observe OS lock ownership. Never acquire any Codex lock, even momentarily.
  if (platform()==='linux') {
    try {
      const major=((info.dev>>8n)&0xfffn)|((info.dev>>32n)&0xfffff000n);
      const minor=(info.dev&0xffn)|((info.dev>>12n)&0xffffff00n);
      const locks=await readFile('/proc/locks','utf8');
      const held=locks.split('\n').some(line=>{
        const value=line.match(/\s([0-9a-f]+):([0-9a-f]+):(\d+)\s/i);
        return value&&BigInt('0x'+value[1])===major&&BigInt('0x'+value[2])===minor&&BigInt(value[3]!)===info.ino;
      });
      return held?'held':'idle';
    } catch{return 'unknown';}
  }
  if (platform()==='darwin') {
    try {
      const result=await promisify(execFile)('lsof',['-F','pl',path],{timeout:2500,maxBuffer:65536});
      // Darwin does not always expose flock mode to lsof. An open maintenance descriptor is conservatively treated as held.
      return /^p\d+/m.test(result.stdout)?'held':'idle';
    } catch(error) {
      const failure=error as NodeJS.ErrnoException&{stdout?:string,stderr?:string,code?:number};
      return failure.code===1&&!failure.stdout&&!failure.stderr?'idle':'unknown';
    }
  }
  return 'unknown';
}
