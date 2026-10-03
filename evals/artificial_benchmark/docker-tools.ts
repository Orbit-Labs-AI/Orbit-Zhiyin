/** Pi's standard tools with a Docker execution backend; no host-tool fallback. */
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { basename } from "node:path";
import {
  createBashTool, createEditTool, createReadTool, createWriteTool,
  type ExtensionAPI,
  type Skill,
} from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  const container = process.env.ORBIT_BENCH_CONTAINER;
  if (!container || !/^orbit-bench-[a-z0-9-]+$/.test(container)) {
    throw new Error("An isolated benchmark container is required");
  }
  const cwd = "/root";
  const docker = process.env.ORBIT_DOCKER_BIN || "docker";
  const assetRoot = "/opt/orbit-personalization";
  let assets: {
    instructions?: string[];
    skills?: { name: string; description: string; path: string }[];
    hooks?: { id: string; script: string; config: string; events: string[] }[];
  } = {};

  function execute(args: string[], input?: string): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const child = spawn(docker, ["exec", "-i", "--workdir", cwd, container!, ...args],
        { stdio: ["pipe", "pipe", "pipe"] });
      const out: Buffer[] = [], err: Buffer[] = [];
      child.stdout.on("data", (chunk) => out.push(chunk));
      child.stderr.on("data", (chunk) => err.push(chunk));
      child.on("error", reject);
      child.on("close", (code) => code === 0 ? resolve(Buffer.concat(out)) :
        reject(new Error(`Container operation failed (${code}): ${Buffer.concat(err)}`)));
      child.stdin.on("error", () => {});
      child.stdin.end(input);
    });
  }
  const python = (code: string, args: string[], input?: string) =>
    execute(["python3", "-c", code, ...args], input);
  const remoteRead = (path: string) => python(
    "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())", [path]);
  const access = async (path: string) => {
    await python("import os,sys;assert os.access(sys.argv[1],os.R_OK), 'File not readable'", [path]);
  };
  const mkdir = async (path: string) => {
    await python("import pathlib,sys;pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=True)", [path]);
  };
  const remoteWrite = async (path: string, content: string) => {
    await python("import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())",
      [path], content);
  };
  const readOps = {
    readFile: remoteRead, access,
    detectImageMimeType: async (path: string) => {
      const mime = (await execute(["file", "--mime-type", "-b", "--", path])).toString().trim();
      return ["image/png", "image/jpeg", "image/gif", "image/webp"].includes(mime) ? mime : null;
    },
  };
  pi.registerTool(createReadTool(cwd, { operations: readOps }));
  pi.registerTool(createWriteTool(cwd, { operations: { writeFile: remoteWrite, mkdir } }));
  pi.registerTool(createEditTool(cwd, { operations: { readFile: remoteRead, writeFile: remoteWrite, access } }));

  const bash = createBashTool(cwd, {
    exposeSessionEnvironment: false,
    operations: {
      exec(command, workingDir, { onData, signal, timeout }) {
        return new Promise((resolve, reject) => {
          // GNU timeout kills the command in the container, not only the host Docker client.
          const seconds = Math.min(timeout || 3600, 3600);
          const child = spawn(docker, ["exec", "-i", "--workdir", workingDir, container!,
            "timeout", "--signal=TERM", "--kill-after=5", String(seconds), "bash", "-c", command],
            { stdio: ["ignore", "pipe", "pipe"] });
          child.stdout.on("data", onData);
          child.stderr.on("data", onData);
          child.on("error", reject);
          const abort = () => {
            // Abort makes the run terminal; stopping its dedicated container kills descendants.
            spawn(docker, ["stop", "--time", "1", container!], { stdio: "ignore" });
            child.kill("SIGTERM");
          };
          if (signal?.aborted) abort();
          signal?.addEventListener("abort", abort, { once: true });
          child.on("close", (code) => {
            signal?.removeEventListener("abort", abort);
            if (signal?.aborted) reject(new Error("aborted"));
            else resolve({ exitCode: code });
          });
        });
      },
    },
  });
  pi.registerTool({
    ...bash,
    async execute(id, params, signal, onUpdate) {
      const result = await bash.execute(id, params, signal, onUpdate);
      // Pi spills long output on the host. Make that same tool output readable in the container.
      const spill = result.details?.fullOutputPath;
      if (spill) {
        const remote = `/tmp/orbit-output/${basename(spill)}`;
        await mkdir("/tmp/orbit-output");
        await remoteWrite(remote, await readFile(spill, "utf8"));
        for (const part of result.content) {
          if (part.type === "text") part.text = part.text.replaceAll(spill, remote);
        }
        result.details!.fullOutputPath = remote;
        const structured = result.structuredContent as { full_output_path?: string } | undefined;
        if (structured?.full_output_path) structured.full_output_path = remote;
      }
      return result;
    },
  });
  pi.on("before_agent_start", (event) => {
    event.systemPromptOptions.cwd = cwd;
    event.systemPromptOptions.appendSystemPrompt = (assets.instructions || []).join("\n\n");
    event.systemPromptOptions.skills = (assets.skills || []).map((skill): Skill => ({
      name: skill.name, description: skill.description, filePath: `${assetRoot}/${skill.path}`,
      baseDir: `${assetRoot}/${skill.path.slice(0, skill.path.lastIndexOf("/"))}`,
      disableModelInvocation: false,
      sourceInfo: { path: `${assetRoot}/${skill.path}`, source: "orbit-benchmark", scope: "temporary", origin: "top-level" },
    }));
  });
  const toolNames: Record<string, string> = { bash: "Bash", read: "Read", edit: "Edit", write: "Write" };
  async function hooks(event: Record<string, unknown>): Promise<{ blocks: string[]; warnings: string[] }> {
    const blocks: string[] = [], warnings: string[] = [];
    for (const hook of assets.hooks || []) {
      if (!hook.events.includes(String(event.hook_event_name))) continue;
      const value = JSON.parse((await python(
        "import json,subprocess,sys;event=sys.stdin.read();" +
        "p=subprocess.run(['python3',sys.argv[1],'--config',sys.argv[2]],input=event,text=True,capture_output=True,timeout=15);" +
        "print(json.dumps({'code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}))",
        [`${assetRoot}/${hook.script}`, `${assetRoot}/${hook.config}`],
        JSON.stringify({ ...event, session_id: container, cwd }),
      )).toString());
      pi.appendEntry("orbit.benchmark.hook", { id: hook.id, event: event.hook_event_name, ...value });
      if (value.code === 2) blocks.push(value.stderr.trim() || "Orbit hook requested another check.");
      else if (value.code !== 0) throw new Error(`Hook ${hook.id} failed: ${value.stderr}`);
      else if (value.stdout.trim()) {
        const response = JSON.parse(value.stdout);
        if (response.systemMessage) warnings.push(response.systemMessage);
      }
    }
    return { blocks, warnings };
  }
  pi.on("tool_call", async (event) => {
    const messages = await hooks({ hook_event_name: "PreToolUse", tool_name: toolNames[event.toolName] || event.toolName,
      tool_input: event.input });
    if (messages.warnings.length) pi.sendMessage({ customType: "orbit.benchmark.hook-feedback",
      content: messages.warnings.join("\n"), display: false }, { deliverAs: "nextTurn" });
    if (messages.blocks.length) return { block: true, reason: messages.blocks.join("\n") };
  });
  pi.on("tool_result", async (event) => {
    const messages = await hooks({ hook_event_name: "PostToolUse", tool_name: toolNames[event.toolName] || event.toolName,
      tool_input: event.input, tool_response: { is_error: event.isError, success: !event.isError, content: event.content } });
    const text = [...messages.blocks, ...messages.warnings].join("\n");
    if (text) return { content: [...event.content, { type: "text" as const, text }] };
  });
  pi.on("agent_end", async () => {
    const messages = await hooks({ hook_event_name: "Stop", stop_hook_active: false });
    const text = [...messages.blocks, ...messages.warnings].join("\n");
    if (text) pi.sendMessage({ customType: "orbit.benchmark.hook-feedback", content: text, display: false },
      { triggerTurn: messages.blocks.length > 0, deliverAs: "followUp" });
  });
  pi.on("session_start", async () => {
    await execute(["true"]);
    if (process.env.ORBIT_BENCH_ASSETS === "1") assets = JSON.parse((await remoteRead(`${assetRoot}/manifest.json`)).toString());
    pi.setActiveTools(["read", "bash", "edit", "write"]);
    pi.appendEntry("orbit.benchmark.runtime", {
      container, cwd, memory: "off", tool_backend: "docker", network: "none",
    });
  });
}
