import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm, realpath } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir, homedir } from 'node:os';
import { ConnectorStore } from '../src/store.ts';
import { normalizeRemote, projectFor, temporaryWorkspace } from '../src/project.ts';

test('remotes normalize across ssh, https, case, trailing .git and ports',()=>{
  assert.equal(normalizeRemote('git@github.com:Example/Repo.git'),'github.com/example/repo');
  assert.equal(normalizeRemote('https://GitHub.com/Example/Repo.git/'),'github.com/example/repo');
  assert.equal(normalizeRemote('ssh://git@gitlab.example.com:2222/Group/Proj.git'),'gitlab.example.com/Group/Proj');
  assert.equal(normalizeRemote('https://Gitlab.Example.com/Group/Proj'),'gitlab.example.com/Group/Proj');
  assert.equal(normalizeRemote('not a remote'),null);
  assert.equal(normalizeRemote(''),null);
});
test('temporary workspace markers and temp roots',()=>{
  assert.equal(temporaryWorkspace('/Users/a/Documents/Codex/2026-10-01/x'),true);
  assert.equal(temporaryWorkspace('/Users/a/.claude/remote/abc'),true);
  assert.equal(temporaryWorkspace('/private/tmp/scratch'),true);
  assert.equal(temporaryWorkspace('/private/tmp/clone',true),false);
  assert.equal(temporaryWorkspace('/Users/a/tmp/project'),false);
});
test('projectFor merges worktrees through commondir, falls back to the git root without origin, and buckets temporary/home dirs',async()=>{
  const root=await realpath(await mkdtemp(join(tmpdir(),'tandem-project-')));
  const store=new ConnectorStore(join(root,'store'));
  try {
    const main=join(root,'main'),wt=join(root,'wt'),bare=join(root,'no-origin');
    await mkdir(join(main,'.git','worktrees','wt'),{recursive:true});await mkdir(join(main,'src'),{recursive:true});
    await writeFile(join(main,'.git','config'),'[core]\n\tbare = false\n[remote "origin"]\n\turl = git@github.com:Example/Repo.git\n');
    await writeFile(join(main,'.git','worktrees','wt','commondir'),'../..\n');
    await mkdir(wt);await writeFile(join(wt,'.git'),`gitdir: ${join(main,'.git','worktrees','wt')}\n`);
    await mkdir(join(bare,'.git'),{recursive:true});await writeFile(join(bare,'.git','config'),'[core]\n\tbare = false\n');
    const row=(id:string|null)=>store.db.prepare('SELECT key_type AS type,key,name,git_remote AS remote FROM project WHERE project_id=?').get(id);
    const a=projectFor(store,join(main,'src'),null),b=projectFor(store,wt,null);
    assert.equal(a,b);assert.deepEqual({...row(a)},{type:'git_remote',key:'github.com/example/repo',name:'repo',remote:'github.com/example/repo'});
    const c=projectFor(store,bare,null);assert.deepEqual({...row(c)},{type:'git_root',key:bare,name:'no-origin',remote:null});
    const d=projectFor(store,'/missing/dir',null);assert.deepEqual({...row(d)},{type:'path',key:'/missing/dir',name:'dir',remote:null});
    const e=projectFor(store,'/missing/dir','https://github.com/Example/Repo');assert.equal(e,a);
    const t1=projectFor(store,'/Users/x/Documents/Codex/one',null),t2=projectFor(store,'/private/tmp/two',null);
    assert.equal(t1,t2);assert.deepEqual({...row(t1)},{type:'bucket',key:'temporary',name:'临时工作区',remote:null});
    assert.deepEqual({...row(projectFor(store,homedir(),null))},{type:'bucket',key:'other',name:'其他',remote:null});
    assert.equal(projectFor(store,null,null),null);
  } finally { store.close(); await rm(root,{recursive:true,force:true}); }
});
