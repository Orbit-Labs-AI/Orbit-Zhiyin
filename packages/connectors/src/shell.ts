/**
 * Effective program head of a shell command, used as a feature/vocabulary key.
 *
 * Port of packages/data/src/tandem_data/shell.py so the staging and canonical pipelines agree:
 * `cd /repo && git status` -> `git status`, `/bin/zsh -lc 'pytest -q'` -> `pytest`,
 * `S=/tmp/x; ls $S` -> `ls`. Heads never contain assignments, absolute paths or arguments other
 * than one recognised subcommand word. The full command line belongs in attrs.command_line.
 */
const SHELLS = new Set(['sh','bash','zsh','dash','ksh','fish','pwsh','powershell']);
// Segments that only change shell state; the next segment holds the real program.
const STATE_ONLY = new Set(['cd','pushd','popd','export','set','unset','source','.','alias','shopt','ulimit','umask','trap',
  'local','declare','typeset','readonly','true',':','wait']);
// Wrappers whose first non-option argument is the real program.
const PREFIXES = new Set(['env','sudo','time','nohup','exec','command','builtin','nice','timeout','stdbuf','caffeinate','xargs']);
const HEADERS = new Set(['for','while','until','case','select','function','esac','done','fi','}',')','in']);
const LEADERS = new Set(['do','then','else','elif','if','!','{','(','time']);
// Programs whose first non-option word is a subcommand worth keeping. `npx` is added here (its
// "subcommand" is the package it runs); the Python list does not have it yet.
const SUBCOMMANDS = new Set(['git','uv','pnpm','npm','npx','yarn','docker','cargo','go','gh','kubectl','brew','pip','pip3','bun',
  'deno','make','swift','xcodebuild','poetry','dotnet','tandem']);
const SEPARATORS = new Set(['&&','||',';','|','&','|&',';;','(',')','\n']);
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=/;
const WORD = /^[A-Za-z0-9][A-Za-z0-9._+-]*$/;
const SUBWORD = /^[a-z][a-z0-9:_-]*$/;
const VALUE_OPTIONS: Record<string,Set<string>> = {
  git:new Set(['-C','-c','--git-dir','--work-tree','--namespace']), uv:new Set(['--directory','--project','--python','-p']),
  pnpm:new Set(['-C','--dir','--filter','-F']), npm:new Set(['--prefix','-w']), docker:new Set(['-H','--context','-c']),
  cargo:new Set(['-C','--manifest-path']), make:new Set(['-C','-f']), gh:new Set(['-R','--repo']), npx:new Set(['-p','--package']),
};
const PUNCTUATION = ';&|()';

class UnbalancedQuote extends Error {}

/** POSIX-like word splitting (quotes, backslash escapes, punctuation runs, newline separators). */
export function shellTokens(command: string): string[] {
  const tokens: string[] = []; let word = '', inWord = false, i = 0;
  const text = command.replace(/\r/g,'\n');
  const flush = (): void => { if (inWord) tokens.push(word); word = ''; inWord = false; };
  while (i < text.length) {
    const c = text[i]!;
    if (c === ' ' || c === '\t') { flush(); i++; continue; }
    if (c === '\n') { flush(); tokens.push('\n'); i++; continue; }
    if (PUNCTUATION.includes(c)) {
      flush(); let run = c; i++;
      while (i < text.length && PUNCTUATION.includes(text[i]!)) run += text[i++]!;
      tokens.push(run); continue;
    }
    if (c === "'") {
      const end = text.indexOf("'",i+1); if (end < 0) throw new UnbalancedQuote();
      word += text.slice(i+1,end); inWord = true; i = end+1; continue;
    }
    if (c === '"') {
      i++; inWord = true;
      while (true) {
        if (i >= text.length) throw new UnbalancedQuote();
        const d = text[i]!;
        if (d === '"') { i++; break; }
        if (d === '\\' && i+1 < text.length && '"\\$`\n'.includes(text[i+1]!)) { word += text[i+1]; i += 2; continue; }
        word += d; i++;
      }
      continue;
    }
    if (c === '\\' && i+1 < text.length) { word += text[i+1]; inWord = true; i += 2; continue; }
    word += c; inWord = true; i++;
  }
  flush();
  return tokens;
}
function segments(tokens: string[]): string[][] {
  const result: string[][] = []; let segment: string[] = [];
  for (const token of tokens) {
    if (SEPARATORS.has(token)) { if (segment.length) result.push(segment); segment = []; }
    else segment.push(token);
  }
  if (segment.length) result.push(segment);
  return result;
}
function program(word: string): string | null {
  if (!word || '$`\'"<>'.includes(word[0]!) || word.includes('=')) return null;
  const base = word.replace(/\/+$/,'').split('/').at(-1)!.split('\\').at(-1)!;
  return WORD.test(base) ? base : null;
}
function quote(word: string): string { return /^[A-Za-z0-9_@%+=:,./-]+$/.test(word) ? word : `'${word.replaceAll("'","'\"'\"'")}'`; }
function shellPayload(args: string[], joined = false): string | null {
  for (const [position,word] of args.entries()) {
    if ((word.startsWith('-') && !word.startsWith('--') && word.slice(1).includes('c')) || word === '-Command' || word === '-command') {
      const rest = args.slice(position+1);
      if (!rest.length) return null;
      return joined && rest.length > 1 ? rest.map(quote).join(' ') : rest[0]!;
    }
    if (!word.startsWith('-')) return null;
  }
  return null;
}
function withSubcommand(name: string, rest: string[]): string {
  if (!SUBCOMMANDS.has(name)) return name;
  const takesValue = VALUE_OPTIONS[name] ?? new Set<string>();
  let index = 0;
  while (index < rest.length && rest[index]!.startsWith('-')) index += takesValue.has(rest[index]!) ? 2 : 1;
  const sub = rest[index];
  return sub !== undefined && SUBWORD.test(sub) && sub.length <= 40 ? `${name} ${sub}` : name;
}
function segmentHead(words: string[], depth: number, joined = true): string | null {
  let index = 0;
  while (index < words.length && (LEADERS.has(words[index]!) || ASSIGNMENT.test(words[index]!))) index++;
  while (index < words.length) {
    const word = words[index]!, name = program(word);
    if (name === null) { if (ASSIGNMENT.test(word)) { index++; continue; } return null; }
    if (HEADERS.has(name) || STATE_ONLY.has(name)) return null;
    if (PREFIXES.has(name)) {
      index++;
      while (index < words.length && (words[index]!.startsWith('-') || ASSIGNMENT.test(words[index]!)
        || ((name === 'timeout' || name === 'nice') && /^\d/.test(words[index]!)))) {
        if (['-u','-n','-s','-k','-C','-g'].includes(words[index]!) && name !== 'xargs') index++;
        index++;
      }
      continue;
    }
    if (SHELLS.has(name)) {
      const payload = shellPayload(words.slice(index+1),joined);
      if (payload !== null) return depth < 3 ? commandHead(payload,depth+1) : null;
      const rest = words.slice(index+1).filter(w=>!w.startsWith('-'));
      return (rest.length ? program(rest[0]!) : null) ?? name;
    }
    return withSubcommand(name,words.slice(index+1));
  }
  return null;
}

/** First effective program of a shell command (string or argv list); never a path. */
export function commandHead(command: unknown, depth = 0): string | null {
  if (Array.isArray(command)) {
    if (!command.length || !command.every(word=>typeof word === 'string')) return null;
    const words = command as string[];
    if (SHELLS.has(program(words[0]!) ?? '')) {
      const payload = shellPayload(words.slice(1));
      if (payload !== null) return depth < 3 ? commandHead(payload,depth+1) : null;
    }
    return segmentHead(words,depth,false);
  }
  if (typeof command !== 'string' || !command.trim()) return null;
  try {
    for (const segment of segments(shellTokens(command))) {
      const head = segmentHead(segment,depth);
      if (head) return head;
    }
    return null;
  } catch (error) {
    if (!(error instanceof UnbalancedQuote)) throw error;
    // Unbalanced quotes: fall back to whitespace words of the first line.
    const words = command.trim().split('\n',1)[0]!.split(/\s+/).filter(Boolean);
    return words.length ? segmentHead(words,depth) : null;
  }
}
