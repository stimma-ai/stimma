import { dirname, fromFileUrl, join, resolve } from "https://deno.land/std@0.220.0/path/mod.ts";

const scriptDir = dirname(Deno.realPathSync(fromFileUrl(import.meta.url)));
const repoRoot = dirname(scriptDir);
const encoder = new TextEncoder();
const PYTHON_STANDALONE_RELEASE = "20260414";
const PYTHON_STANDALONE_VERSION = "3.11.15+20260414";

type RunOptions = {
  cwd?: string;
  env?: Record<string, string>;
  check?: boolean;
};

type CaptureOptions = {
  cwd?: string;
  env?: Record<string, string>;
};

type DevProcess = {
  label: string;
  child: Deno.ChildProcess;
  status: Promise<Deno.CommandStatus>;
};

type ProcessEntry = {
  pid: number;
  ppid: number;
  pgid: number;
};

type TerminationSignal = "SIGTERM" | "SIGKILL";

const DEV_HOST = "127.0.0.1";
const LOCALHOSTS = [DEV_HOST, "::1"];
const VITE_DEV_ARGS = ["run", "dev", "--", "--host", DEV_HOST, "--strictPort"];
const DEFAULT_BACKEND_PORT = 9191;
const DEFAULT_FRONTEND_PORT = 9192;
// Hiro uses 9292/9293 for defaults and 9300-9399 for sandboxes.
// Keep Stimma's non-default sandboxes in their own lane so both apps can be
// developed side-by-side without port collisions.
const FORK_PORT_BASE = 9400;
const FORK_PORT_LIMIT = 9500;
const LEGACY_HIRO_COLLIDING_PORT_BASE = 9300;
const LEGACY_HIRO_COLLIDING_PORT_LIMIT = 9400;
const LOCAL_ENV_FILENAME = ".env.local";
const SENSITIVE_ENV_NAME_RE = /(TOKEN|SECRET|KEY|PASSWORD|AUTH|CLIENT_ID)/i;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function run(cmd: string, args: string[] = [], opts: RunOptions = {}): Promise<number> {
  const command = new Deno.Command(cmd, {
    args,
    cwd: opts.cwd,
    env: { ...Deno.env.toObject(), ...(opts.env || {}) },
    stdin: "inherit",
    stdout: "inherit",
    stderr: "inherit",
  });
  const child = command.spawn();
  const { code } = await child.status;
  if (opts.check !== false && code !== 0) {
    console.error(`Command failed with exit code ${code}: ${cmd} ${args.join(" ")}`);
    Deno.exit(code);
  }
  return code;
}

function cleanEnvValue(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function parseEnvFile(content: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const normalized = line.startsWith("export ") ? line.slice("export ".length).trim() : line;
    const match = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(normalized);
    if (!match) continue;
    env[match[1]] = cleanEnvValue(match[2]);
  }
  return env;
}

async function loadLocalEnvOverrides(): Promise<Record<string, string>> {
  const path = join(repoRoot, LOCAL_ENV_FILENAME);
  try {
    return parseEnvFile(await Deno.readTextFile(path));
  } catch (err) {
    if (err instanceof Deno.errors.NotFound) return {};
    throw err;
  }
}

function summarizeEnvOverrides(env: Record<string, string>): string {
  return Object.keys(env)
    .sort()
    .map((key) => SENSITIVE_ENV_NAME_RE.test(key) ? `${key}=<redacted>` : `${key}=${env[key]}`)
    .join(", ");
}

function prefixOutput(label: string, stream: ReadableStream<Uint8Array> | null): Promise<void> {
  if (!stream) return Promise.resolve();
  const decoder = new TextDecoder();
  const prefix = `[${label}] `;
  let buffered = "";

  return (async () => {
    const reader = stream.getReader();
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffered += decoder.decode(value, { stream: true });
        const lines = buffered.split(/\r?\n/);
        buffered = lines.pop() || "";
        for (const line of lines) {
          console.log(`${prefix}${line}`);
        }
      }
      buffered += decoder.decode();
      if (buffered) console.log(`${prefix}${buffered}`);
    } catch (err) {
      console.error(`${prefix}output read failed: ${err}`);
    }
  })();
}

function spawnDevProcess(label: string, cmd: string, args: string[], opts: RunOptions = {}): DevProcess {
  const command = new Deno.Command(cmd, {
    args,
    cwd: opts.cwd,
    env: { ...Deno.env.toObject(), ...(opts.env || {}) },
    stdin: "null",
    stdout: "piped",
    stderr: "piped",
  });
  const child = command.spawn();
  void prefixOutput(label, child.stdout);
  void prefixOutput(label, child.stderr);
  return { label, child, status: child.status };
}

async function unixProcessTable(): Promise<ProcessEntry[]> {
  const out = await runCapture("ps", ["-axo", "pid=,ppid=,pgid="]);
  if (out.code !== 0) return [];
  return out.stdout.split(/\r?\n/)
    .map((line) => line.trim().split(/\s+/).map((part) => Number(part)))
    .filter((parts) => parts.length >= 3 && parts.every(Number.isFinite))
    .map(([pid, ppid, pgid]) => ({ pid, ppid, pgid }));
}

function unixDescendantPids(rootPid: number, table: ProcessEntry[]): number[] {
  const childrenByParent = new Map<number, number[]>();
  for (const { pid, ppid } of table) {
    if (!childrenByParent.has(ppid)) childrenByParent.set(ppid, []);
    childrenByParent.get(ppid)!.push(pid);
  }

  const descendants: number[] = [];
  const queue = [...(childrenByParent.get(rootPid) || [])];
  while (queue.length > 0) {
    const pid = queue.shift()!;
    descendants.push(pid);
    queue.push(...(childrenByParent.get(pid) || []));
  }
  return descendants;
}

async function signalProcessTree(proc: DevProcess, signal: TerminationSignal): Promise<void> {
  const rootPid = proc.child.pid;

  if (Deno.build.os === "windows") {
    const args = signal === "SIGKILL"
      ? ["/PID", String(rootPid), "/T", "/F"]
      : ["/PID", String(rootPid), "/T"];
    await runCapture("taskkill", args);
    return;
  }

  const table = await unixProcessTable();
  const descendants = unixDescendantPids(rootPid, table);
  const pids = [rootPid, ...descendants].filter((pid) => pid !== Deno.pid);
  const pidSet = new Set(pids);
  const ownPgid = table.find((entry) => entry.pid === Deno.pid)?.pgid;
  const childOwnedPgids = new Set(
    table
      .filter((entry) => pidSet.has(entry.pid) && entry.pgid > 0 && entry.pgid !== ownPgid)
      .map((entry) => entry.pgid),
  );

  for (const pgid of childOwnedPgids) {
    try {
      Deno.kill(-pgid, signal);
    } catch {
      // Process group already exited or is otherwise unavailable.
    }
  }

  for (const pid of pids) {
    try {
      Deno.kill(pid, signal);
    } catch {
      // Process already exited or is otherwise unavailable.
    }
  }
}

async function waitForDevProcessesToExit(processes: DevProcess[], timeoutMs: number): Promise<boolean> {
  const done = Promise.allSettled(processes.map((proc) => proc.status)).then(() => true);
  const timedOut = sleep(timeoutMs).then(() => false);
  return await Promise.race([done, timedOut]);
}

async function terminateDevProcesses(processes: DevProcess[]): Promise<void> {
  if (processes.length === 0) return;

  await Promise.all(processes.map((proc) => signalProcessTree(proc, "SIGTERM")));
  if (await waitForDevProcessesToExit(processes, 8000)) return;

  console.warn("[dev all] Some processes did not exit after SIGTERM; sending SIGKILL.");
  await Promise.all(processes.map((proc) => signalProcessTree(proc, "SIGKILL")));
  await waitForDevProcessesToExit(processes, 3000);
}

async function isTcpPortOpen(hostname: string, port: number, timeoutMs = 500): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const connect = Deno.connect({ hostname, port });
    const timeout = new Promise<null>((resolve) => {
      timer = setTimeout(() => resolve(null), timeoutMs);
    });
    const conn = await Promise.race([connect, timeout]);
    if (!conn) return false;
    conn.close();
    return true;
  } catch {
    return false;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

async function assertTcpPortAvailable(port: number, label: string): Promise<void> {
  for (const hostname of LOCALHOSTS) {
    if (await isTcpPortOpen(hostname, port, 150)) {
      throw new Error(
        `${label} port ${port} is already in use on ${hostname}. ` +
          "Stop the existing dev process or choose another sandbox before running 'stimma dev all'.",
      );
    }
  }

  for (const hostname of LOCALHOSTS) {
    let listener: Deno.Listener | null = null;
    try {
      listener = Deno.listen({ hostname, port });
    } catch (err) {
      if (hostname === "::1" && !(await isTcpPortOpen(hostname, port, 150))) {
        continue;
      }
      const detail = err instanceof Error ? err.message : String(err);
      throw new Error(`${label} port ${port} is not available on ${hostname}: ${detail}`);
    } finally {
      listener?.close();
    }
  }
}

async function warnIfTcpPortStillOpen(port: number, label: string, timeoutMs = 5000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const open = await Promise.all(LOCALHOSTS.map((hostname) => isTcpPortOpen(hostname, port, 150)));
    if (!open.some(Boolean)) return;
    await sleep(250);
  }

  console.warn(`[dev all] ${label} port ${port} is still listening after shutdown.`);
}

async function waitForReadyOrExit(processes: DevProcess[], ready: Promise<void>): Promise<void> {
  const firstExit = Promise.race(processes.map(async (proc) => ({
    type: "exit" as const,
    proc,
    status: await proc.status,
  })));
  const readyResult = ready.then(() => ({ type: "ready" as const }));
  const result = await Promise.race([firstExit, readyResult]);
  if (result.type === "ready") return;

  throw new Error(
    `${result.proc.label} exited before the dev stack was ready ` +
      `(code ${result.status.code}); stopping remaining processes.`,
  );
}

async function waitForTcpPort(port: number, label: string, timeoutMs = 60000, hostnames = LOCALHOSTS): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const hostname of hostnames) {
      if (await isTcpPortOpen(hostname, port, 250)) return;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${label} on port ${port}`);
}

async function runCapture(cmd: string, args: string[] = [], opts: CaptureOptions = {}): Promise<{
  code: number;
  stdout: string;
  stderr: string;
}> {
  const command = new Deno.Command(cmd, {
    args,
    cwd: opts.cwd,
    env: { ...Deno.env.toObject(), ...(opts.env || {}) },
    stdin: "null",
    stdout: "piped",
    stderr: "piped",
  });
  const out = await command.output();
  return {
    code: out.code,
    stdout: new TextDecoder().decode(out.stdout),
    stderr: new TextDecoder().decode(out.stderr),
  };
}

const CHANNEL_BUNDLE_IDS: Record<string, string> = {
  debug: "ai.stimma.stimma.debug",
  sandbox: "ai.stimma.stimma.debug",
  canary: "ai.stimma.stimma.canary",
  beta: "ai.stimma.stimma.beta",
  production: "ai.stimma.stimma",
  stable: "ai.stimma.stimma",
};

function getDataDir(bundleId: string, sandbox: string): string {
  const home = Deno.env.get("HOME") || Deno.env.get("USERPROFILE") || "";
  if (Deno.build.os === "darwin") {
    return join(home, "Library", "Application Support", bundleId, sandbox);
  }
  if (Deno.build.os === "windows") {
    const localAppData = Deno.env.get("LOCALAPPDATA") || join(home, "AppData", "Local");
    return join(localAppData, bundleId, sandbox);
  }
  const xdgData = Deno.env.get("XDG_DATA_HOME") || join(home, ".local", "share");
  return join(xdgData, bundleId, sandbox);
}

function getCacheDir(bundleId: string, sandbox: string): string {
  const home = Deno.env.get("HOME") || Deno.env.get("USERPROFILE") || "";
  if (Deno.build.os === "darwin") {
    return join(home, "Library", "Caches", bundleId, sandbox);
  }
  if (Deno.build.os === "windows") {
    const localAppData = Deno.env.get("LOCALAPPDATA") || join(home, "AppData", "Local");
    return join(localAppData, bundleId, sandbox);
  }
  const xdgCache = Deno.env.get("XDG_CACHE_HOME") || join(home, ".cache");
  return join(xdgCache, bundleId, sandbox);
}

function getBundleDataRoot(bundleId: string): string {
  const home = Deno.env.get("HOME") || Deno.env.get("USERPROFILE") || "";
  if (Deno.build.os === "darwin") {
    return join(home, "Library", "Application Support", bundleId);
  }
  if (Deno.build.os === "windows") {
    const localAppData = Deno.env.get("LOCALAPPDATA") || join(home, "AppData", "Local");
    return join(localAppData, bundleId);
  }
  const xdgData = Deno.env.get("XDG_DATA_HOME") || join(home, ".local", "share");
  return join(xdgData, bundleId);
}

function getBundleCacheRoot(bundleId: string): string {
  const home = Deno.env.get("HOME") || Deno.env.get("USERPROFILE") || "";
  if (Deno.build.os === "darwin") {
    return join(home, "Library", "Caches", bundleId);
  }
  if (Deno.build.os === "windows") {
    const localAppData = Deno.env.get("LOCALAPPDATA") || join(home, "AppData", "Local");
    return join(localAppData, bundleId);
  }
  const xdgCache = Deno.env.get("XDG_CACHE_HOME") || join(home, ".cache");
  return join(xdgCache, bundleId);
}

type SandboxPorts = {
  server: number;
  frontend: number;
};

function forkJsonPath(bundleId: string, sandbox: string): string {
  return join(getDataDir(bundleId, sandbox), ".fork.json");
}

async function readSandboxPorts(bundleId: string, sandbox: string): Promise<SandboxPorts | null> {
  try {
    const data = JSON.parse(await Deno.readTextFile(forkJsonPath(bundleId, sandbox)));
    const server = Number(data.server_port);
    const frontend = Number(data.frontend_port);
    if (Number.isInteger(server) && Number.isInteger(frontend) && server > 0 && frontend > 0) {
      return { server, frontend };
    }
  } catch {
    // Missing or unreadable .fork.json means no assigned ports yet.
  }
  return null;
}

async function writeSandboxPorts(bundleId: string, sandbox: string, ports: SandboxPorts): Promise<void> {
  const dataDir = getDataDir(bundleId, sandbox);
  await Deno.mkdir(dataDir, { recursive: true });
  const payload = {
    server_port: ports.server,
    frontend_port: ports.frontend,
  };
  await Deno.writeTextFile(forkJsonPath(bundleId, sandbox), JSON.stringify(payload, null, 2) + "\n");
}

async function nextSandboxPorts(bundleId: string): Promise<SandboxPorts> {
  const root = getBundleDataRoot(bundleId);
  const usedPorts = new Set<number>([DEFAULT_BACKEND_PORT, DEFAULT_FRONTEND_PORT]);

  try {
    for await (const entry of Deno.readDir(root)) {
      if (!entry.isDirectory) continue;
      const ports = await readSandboxPorts(bundleId, entry.name);
      if (!ports) continue;
      usedPorts.add(ports.server);
      usedPorts.add(ports.frontend);
    }
  } catch {
    // Bundle directory may not exist yet.
  }

  for (let port = FORK_PORT_BASE; port < FORK_PORT_LIMIT; port += 2) {
    const alreadyAssigned = usedPorts.has(port) || usedPorts.has(port + 1);
    const currentlyOpen = (await Promise.all(
      LOCALHOSTS.flatMap((hostname) => [
        isTcpPortOpen(hostname, port, 150),
        isTcpPortOpen(hostname, port + 1, 150),
      ]),
    )).some(Boolean);
    if (!alreadyAssigned && !currentlyOpen) {
      return { server: port, frontend: port + 1 };
    }
  }

  throw new Error(`No available sandbox ports in range ${FORK_PORT_BASE}-${FORK_PORT_LIMIT - 1}`);
}

async function getSandboxPorts(bundleId: string, sandbox: string): Promise<{ server: number; frontend: number }> {
  const existing = await readSandboxPorts(bundleId, sandbox);
  if (existing) {
    const inLegacyHiroRange =
      sandbox !== "default" &&
      existing.server >= LEGACY_HIRO_COLLIDING_PORT_BASE &&
      existing.server < LEGACY_HIRO_COLLIDING_PORT_LIMIT;
    if (!inLegacyHiroRange) return existing;

    const ports = await nextSandboxPorts(bundleId);
    await writeSandboxPorts(bundleId, sandbox, ports);
    console.log(
      `Sandbox '${sandbox}': moved ports out of Hiro's range ` +
        `backend=:${existing.server} frontend=:${existing.frontend} -> ` +
        `backend=:${ports.server} frontend=:${ports.frontend}`,
    );
    return ports;
  }

  if (sandbox === "default") {
    return { server: DEFAULT_BACKEND_PORT, frontend: DEFAULT_FRONTEND_PORT };
  }

  const ports = await nextSandboxPorts(bundleId);
  await writeSandboxPorts(bundleId, sandbox, ports);
  console.log(`Sandbox '${sandbox}': assigned ports backend=:${ports.server} frontend=:${ports.frontend}`);
  return ports;
}

async function requireSandboxBackendStopped(
  bundleId: string,
  sandbox: string,
  operation: string,
): Promise<void> {
  const ports = await getSandboxPorts(bundleId, sandbox);
  for (const hostname of LOCALHOSTS) {
    if (await isTcpPortOpen(hostname, ports.server, 200)) {
      console.error(
        `Refusing to ${operation} while the backend is listening on ${hostname}:${ports.server}. ` +
          `Stop Stimma for sandbox '${sandbox}' first so its SQLite databases are consistent.`,
      );
      Deno.exit(1);
    }
  }
}

function sandboxIdentifier(baseBundleId: string, sandbox: string): string {
  if (sandbox === "default") return baseBundleId;
  return `${baseBundleId}.${sandboxSafeSegment(sandbox)}`;
}

function sandboxSafeSegment(sandbox: string): string {
  return sandbox
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    || "sandbox";
}

function printUsage(): never {
  console.log(`Stimma Development CLI

Usage: stimma [FLAGS] <command> <subcommand>

Flags:
  --prod              Shorthand for --channel=production
  --channel CHANNEL   Release channel: debug (default), sandbox, canary, beta, production
                      (--channel=CHANNEL is also accepted)
  --sandbox NAME      Sandbox name (default: "default"; --sandbox=NAME also accepted)
  --official          dev/run only: set STIMMA_DISTRIBUTION=official in the child
                      process so telemetry, consent UI, thumbs, and crash reports
                      behave like an official build (events go to the configured
                      cloud; app_branch stays 'dev' on the debug channel)

Commands:
  dev frontend    Run Vite dev server with HMR (default port 9192)
  dev backend     Run Python backend with nodemon (default port 9191)
  dev backend2    Run Rust backend (default port 9191)
  dev app         Run Tauri in dev mode
  dev all         Run backend + frontend + Tauri together with merged logs
  run backend     Run backend without file watching
  run frontend    Build and serve frontend (no HMR)
  run app         Run Tauri app (release, no watching)
  tail backend    Tail backend logs
  tail app        Tail Tauri app logs
  app build       Build packaged app with portable backend
  app build --release  Build with polished DMG (macOS)
  app run         Run built app
  app install     Install built app
  config edit     Open config.yaml in $EDITOR
  stimpacks dev [path]   Use a stimpacks dir as the live authority for built-in stimpacks
                      (default: sibling stimma-skills repo). Shadows installed copies.
  stimpacks dev --off    Clear the dev stimpacks override
  stimpacks validate PATH...  Validate stimpack directories with the real loader
                      (skills, environments, lib modules; non-zero exit on errors)
  backup          Create timestamped local snapshot (source backend must be stopped)
  lint backend    Run ruff over the backend (undefined names, syntax errors)
  lint frontend-dead-code
                  Run Knip's conservative unused frontend file check
  test backend    Run backend pytest tests
  test acceptance Run the release acceptance lane (fresh sandbox + fake tools)
  test acceptance --headed --slow-mo=250  Watch Chromium run the lane slowly
  test cv2-parity Run cv2 parity proof (uses optional cv2-parity extra)
  doctor assets     Read-only Asset/Media integrity audit
  doctor assets --verify-hashes  Also hash every managed payload
  oss             Regenerate ATTRIBUTION.md dependency tables from the current
                  lockfiles (run after dependency changes; review + commit the diff)
  migrate-to-managed-storage [--profile ID] [--legacy-generated-root PATH]
                  [--legacy-uploads-root PATH] (root flags are repeatable)
                  [--delete-untracked-legacy-files]
                  Dry-run normalization of retained Stimma-created payloads;
                  add --apply --yes after backing up and stopping Stimma
  rewrite prompts --replace OLD NEW [--replace OLD NEW ...]
                  Dry-run a literal prompt/history rewrite across every profile DB
                  and associated PNG/JPEG metadata; add --apply --yes to write
  tag beta [X.Y.Z]    Tag HEAD as the next beta (train = next production version)
                      (canary builds are automatic on push to main — not tag-driven)
  promote production  Promote the latest beta's commit to a production release
                      [--ref REF] hotfix override: promote an explicit git ref
                      [--yes] skip the confirmation prompt
  dir               Print data directory path
  fork              List all sandboxes with sizes and ports
  fork create NAME  Snapshot default sandbox to a new named sandbox
  fork create NAME --empty  Create a FRESH first-run sandbox (empty except
                      .fork.json with assigned ports) — backend boots it
                      as a new install: config auto-init, consent undetermined
  fork destroy NAME [--yes]  Delete a named sandbox (data + cache); --yes skips
                      the confirmation prompt (required for non-interactive use)
  bd [args...]    Passthrough to beads CLI`);
  Deno.exit(1);
}

type SemverCore = {
  major: number;
  minor: number;
  patch: number;
};

type PreTag = SemverCore & {
  channel: "alpha" | "beta";
  number: number;
};

function fmtCore(core: SemverCore): string {
  return `${core.major}.${core.minor}.${core.patch}`;
}

function parseCore(version: string): SemverCore | null {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(version.trim());
  if (!m) return null;
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]) };
}

function parseProductionTag(tag: string): SemverCore | null {
  const m = /^v(\d+)\.(\d+)\.(\d+)$/.exec(tag.trim());
  if (!m) return null;
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]) };
}

function parsePreTag(tag: string): PreTag | null {
  const m = /^v(\d+)\.(\d+)\.(\d+)-(alpha|beta)\.(\d+)$/.exec(tag.trim());
  if (!m) return null;
  return {
    major: Number(m[1]),
    minor: Number(m[2]),
    patch: Number(m[3]),
    channel: m[4] as "alpha" | "beta",
    number: Number(m[5]),
  };
}

function compareCore(a: SemverCore, b: SemverCore): number {
  if (a.major !== b.major) return a.major - b.major;
  if (a.minor !== b.minor) return a.minor - b.minor;
  return a.patch - b.patch;
}

function bumpPatch(core: SemverCore): SemverCore {
  return { major: core.major, minor: core.minor, patch: core.patch + 1 };
}

function maxCore(values: SemverCore[]): SemverCore | null {
  if (values.length === 0) return null;
  return [...values].sort(compareCore).at(-1) || null;
}

function maxPreTag(values: PreTag[]): PreTag | null {
  if (values.length === 0) return null;
  return [...values].sort((a, b) => {
    const coreCmp = compareCore(a, b);
    if (coreCmp !== 0) return coreCmp;
    return a.number - b.number;
  }).at(-1) || null;
}

async function listTags(): Promise<string[]> {
  const out = await runCapture("git", ["tag", "--list", "v*"], { cwd: repoRoot });
  if (out.code !== 0) {
    console.error(out.stderr || "Failed to list git tags.");
    Deno.exit(out.code);
  }
  return out.stdout.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}

async function warnIfDirtyWorktree(): Promise<void> {
  const out = await runCapture("git", ["status", "--porcelain"], { cwd: repoRoot });
  if (out.code !== 0) {
    console.warn("Warning: unable to determine worktree status.");
    return;
  }
  if (out.stdout.trim()) {
    console.warn("Warning: repository has uncommitted changes.");
    const answer = prompt("Continue anyway? (y/N)");
    if (answer?.toLowerCase() !== "y") {
      console.log("Aborted.");
      Deno.exit(1);
    }
  }
}

async function tagExists(tagName: string): Promise<boolean> {
  const out = await runCapture("git", ["show-ref", "--tags", "--verify", `refs/tags/${tagName}`], { cwd: repoRoot });
  return out.code === 0;
}

async function createAndPushTag(tagName: string, commit?: string): Promise<void> {
  if (await tagExists(tagName)) {
    console.error(`Tag already exists: ${tagName}`);
    Deno.exit(1);
  }
  // Annotated tag with a message — works regardless of the repo's
  // tag.gpgSign / forceSignAnnotated git config (a lightweight `git tag <name>`
  // fails with "no tag message?" when annotation is forced).
  const tagArgs = ["tag", "-a", tagName, "-m", `Release ${tagName}`];
  if (commit) tagArgs.push(commit);
  await run("git", tagArgs, { cwd: repoRoot });
  await run("git", ["push", "origin", `refs/tags/${tagName}`], { cwd: repoRoot });
  console.log(`Tagged and pushed: ${tagName}`);
}

async function commandTag(args: string[]): Promise<void> {
  const mode = args[0];
  const explicit = args[1];

  if (mode === "production") {
    console.error("`stimma tag production` is gone — production is a promotion of a tested beta commit,");
    console.error("not a build of whatever HEAD happens to be.");
    console.error("Use: stimma promote production            (promotes the latest beta)");
    console.error("     stimma promote production --ref REF  (hotfix: promote an explicit git ref)");
    Deno.exit(1);
  }

  if (mode === "alpha" || mode === "canary") {
    console.error("`stimma tag alpha`/`stimma tag canary` is gone — canary builds are automatic on push to");
    console.error("main (see .github/workflows/canary.yml), not cut from a tag.");
    console.error("To build one manually, dispatch the Canary workflow instead.");
    Deno.exit(1);
  }

  if (mode !== "beta" || args.length > 2) {
    console.error("Usage: stimma tag beta [X.Y.Z]");
    Deno.exit(1);
  }

  await warnIfDirtyWorktree();

  const tags = await listTags();
  const productionTags = tags.map(parseProductionTag).filter((v): v is SemverCore => v !== null);
  const preTags = tags.map(parsePreTag).filter((v): v is PreTag => v !== null);
  const latestProduction = maxCore(productionTags);

  const channel = mode;
  let base: SemverCore;
  if (explicit) {
    const parsed = parseCore(explicit);
    if (!parsed) {
      console.error(`Invalid version '${explicit}'. Expected X.Y.Z.`);
      Deno.exit(1);
    }
    base = parsed;
  } else {
    // Pre-release trains always carry the NEXT production version. They
    // rebase automatically when production moves, so a train can never fall
    // below the shipped version (where the updater would stop offering it).
    base = latestProduction ? bumpPatch(latestProduction) : { major: 0, minor: 1, patch: 0 };
  }

  const existingForBase = preTags
    .filter((t) => t.channel === channel)
    .filter((t) => compareCore(t, base) === 0);
  const nextN = (existingForBase.length > 0 ? Math.max(...existingForBase.map((t) => t.number)) : 0) + 1;
  await createAndPushTag(`v${fmtCore(base)}-${channel}.${nextN}`);
}

async function commandPromote(args: string[]): Promise<void> {
  const target = args[0];
  const rest = args.slice(1);
  let ref: string | null = null;
  let yes = false;
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === "--yes" || a === "-y") yes = true;
    else if (a === "--ref") ref = rest[++i] ?? null;
    else if (a.startsWith("--ref=")) ref = a.slice("--ref=".length);
    else {
      console.error(`Unknown argument: ${a}`);
      console.error("Usage: stimma promote production [--ref REF] [--yes]");
      Deno.exit(1);
    }
  }

  if (target !== "production" || (ref !== null && !ref.trim())) {
    console.error("Usage: stimma promote production [--ref REF] [--yes]");
    Deno.exit(1);
  }

  const tags = await listTags();
  const productionTags = tags.map(parseProductionTag).filter((v): v is SemverCore => v !== null);
  const preTags = tags.map(parsePreTag).filter((v): v is PreTag => v !== null);
  const latestProduction = maxCore(productionTags);
  const latestBeta = maxPreTag(preTags.filter((t) => t.channel === "beta"));

  if (!latestBeta) {
    console.error("No beta tags found. Cut one first: stimma tag beta");
    Deno.exit(1);
  }
  const betaName = `v${fmtCore(latestBeta)}-beta.${latestBeta.number}`;

  if (latestProduction && compareCore(latestBeta, latestProduction) <= 0) {
    console.error(`Latest beta ${betaName} is not ahead of production v${fmtCore(latestProduction)}.`);
    console.error("Cut a fresh beta from the code you want to ship: stimma tag beta");
    Deno.exit(1);
  }

  const commitRef = ref ?? betaName;
  const resolved = await runCapture("git", ["rev-parse", "--verify", `${commitRef}^{commit}`], { cwd: repoRoot });
  if (resolved.code !== 0) {
    console.error(`Cannot resolve '${commitRef}' to a commit.`);
    Deno.exit(1);
  }
  const commit = resolved.stdout.trim();
  const describe = await runCapture("git", ["log", "-1", "--format=%h %ad %s", "--date=short", commit], { cwd: repoRoot });

  const prodName = `v${fmtCore(latestBeta)}`;

  // Release notes are required to ship. They are read from the working tree
  // (not the promoted commit) because notes are often polished after the beta
  // was tagged; CI publishes them from main (see release-notes.yml).
  const notesPath = join(repoRoot, "releasenotes", `${prodName}.md`);
  let notesBody = "";
  try {
    notesBody = await Deno.readTextFile(notesPath);
  } catch {
    // fall through to the empty check
  }
  if (!notesBody.trim()) {
    console.error(`Release notes missing: releasenotes/${prodName}.md`);
    console.error("Write them (user-facing, markdown), commit to main, and re-run.");
    Deno.exit(1);
  }

  console.log(`Promoting ${ref ? `ref '${ref}'` : betaName} to ${prodName}`);
  console.log(`  commit: ${describe.stdout.trim() || commit}`);
  if (ref) {
    console.log(`  note: overriding the beta commit; ${prodName} will NOT match ${betaName}'s build.`);
  }
  const drift = await runCapture("git", ["rev-list", "--count", `${commit}..main`], { cwd: repoRoot });
  const driftCount = Number(drift.stdout.trim());
  if (drift.code === 0 && Number.isFinite(driftCount) && driftCount > 0) {
    console.log(`  note: main is ${driftCount} commit(s) ahead of this commit — those are NOT in this release.`);
  }

  if (!yes) {
    if (!Deno.stdin.isTerminal()) {
      console.log("Non-interactive shell: re-run with --yes to confirm this promotion.");
      Deno.exit(1);
    }
    const answer = prompt(`Tag ${prodName} from this commit and start the production release? (y/N)`);
    if (answer?.toLowerCase() !== "y") {
      console.log("Aborted.");
      Deno.exit(1);
    }
  }

  await createAndPushTag(prodName, commit);
}

async function detectTargetTriple(): Promise<string> {
  const cmd = new Deno.Command("rustc", { args: ["-vV"], stdout: "piped", stderr: "inherit" });
  const out = await cmd.output();
  if (!out.success) {
    throw new Error("Failed to detect rust target triple");
  }
  const text = new TextDecoder().decode(out.stdout);
  const hostLine = text.split("\n").find((line) => line.startsWith("host: "));
  if (!hostLine) {
    throw new Error("rustc output missing host triple");
  }
  return hostLine.replace("host: ", "").trim();
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await Deno.stat(path);
    return true;
  } catch {
    return false;
  }
}

async function copyDir(src: string, dest: string): Promise<void> {
  await Deno.mkdir(dest, { recursive: true });
  for await (const entry of Deno.readDir(src)) {
    const srcPath = join(src, entry.name);
    const destPath = join(dest, entry.name);
    if (entry.isDirectory) {
      await copyDir(srcPath, destPath);
    } else if (entry.isFile) {
      await Deno.copyFile(srcPath, destPath);
    }
  }
}

async function copyDataDirSnapshot(src: string, dest: string): Promise<void> {
  if (await pathExists(dest)) {
    throw new Error(`Snapshot destination already exists: ${dest}`);
  }

  const partialDest = `${dest}.partial-${crypto.randomUUID()}`;
  let copyCode: number;
  if (Deno.build.os === "darwin") {
    // APFS clones have independent inodes while sharing unchanged data blocks.
    // ditto also preserves the source tree's own hard-link topology, symlinks,
    // resource forks, xattrs, and ACLs. It falls back to a byte copy when the
    // source and destination are not on clone-capable filesystems.
    copyCode = await run("ditto", [
      "--clone",
      "--rsrc",
      "--extattr",
      "--acl",
      "--qtn",
      "--preserveHFSCompression",
      src,
      partialDest,
    ], { check: false });
  } else if (Deno.build.os === "linux") {
    // GNU cp preserves hard links and uses filesystem reflinks when available,
    // falling back to an ordinary archive copy otherwise.
    copyCode = await run(
      "cp",
      ["--archive", "--reflink=auto", "--", src, partialDest],
      { check: false },
    );
  } else {
    throw new Error(`Copy-on-write snapshots are not supported on ${Deno.build.os} yet.`);
  }

  if (copyCode !== 0) {
    await Deno.remove(partialDest, { recursive: true }).catch(() => {});
    console.error(`Snapshot copy failed with exit code ${copyCode}; partial output was removed.`);
    Deno.exit(copyCode);
  }

  // Only a fully copied tree receives the user-visible destination name.
  await Deno.rename(partialDest, dest);
}

async function copyDirFiltered(src: string, dest: string, shouldExclude: (relativePath: string, entry: Deno.DirEntry) => boolean, prefix = ""): Promise<void> {
  await Deno.mkdir(dest, { recursive: true });
  for await (const entry of Deno.readDir(src)) {
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (shouldExclude(relativePath, entry)) continue;

    const srcPath = join(src, entry.name);
    const destPath = join(dest, entry.name);
    if (entry.isDirectory) {
      await copyDirFiltered(srcPath, destPath, shouldExclude, relativePath);
    } else if (entry.isFile) {
      await Deno.mkdir(dirname(destPath), { recursive: true });
      await Deno.copyFile(srcPath, destPath);
    }
  }
}

async function removeDirsByName(root: string, names: Set<string>): Promise<void> {
  if (!await pathExists(root)) return;
  for await (const entry of Deno.readDir(root)) {
    if (!entry.isDirectory) continue;
    const path = join(root, entry.name);
    if (names.has(entry.name)) {
      await Deno.remove(path, { recursive: true });
    } else {
      await removeDirsByName(path, names);
    }
  }
}

async function removeMatching(root: string, predicate: (path: string, entry: Deno.DirEntry) => boolean): Promise<void> {
  if (!await pathExists(root)) return;
  for await (const entry of Deno.readDir(root)) {
    const path = join(root, entry.name);
    if (predicate(path, entry)) {
      await Deno.remove(path, { recursive: entry.isDirectory });
    } else if (entry.isDirectory) {
      await removeMatching(path, predicate);
    }
  }
}

async function dirSize(root: string): Promise<{ files: number; bytes: number }> {
  let files = 0;
  let bytes = 0;
  if (!await pathExists(root)) return { files, bytes };
  for await (const entry of Deno.readDir(root)) {
    const path = join(root, entry.name);
    if (entry.isDirectory) {
      const child = await dirSize(path);
      files += child.files;
      bytes += child.bytes;
    } else if (entry.isFile) {
      files++;
      bytes += (await Deno.stat(path)).size;
    }
  }
  return { files, bytes };
}

async function buildWatchdog(target: string): Promise<void> {
  const watchdogDir = join(repoRoot, "src-tauri", "watchdog");
  await run("cargo", ["build", "--release"], { cwd: watchdogDir });

  const ext = Deno.build.os === "windows" ? ".exe" : "";
  const src = join(watchdogDir, "target", "release", `stimma-watchdog${ext}`);
  const destDir = join(repoRoot, "src-tauri", "binaries");
  await Deno.mkdir(destDir, { recursive: true });
  await Deno.copyFile(src, join(destDir, `stimma-watchdog-${target}${ext}`));
}

async function downloadWindowsStandalonePython(target: string, pythonStandaloneDir: string): Promise<string> {
  await Deno.mkdir(pythonStandaloneDir, { recursive: true });

  for await (const entry of Deno.readDir(pythonStandaloneDir)) {
    if (
      entry.isFile &&
      entry.name.startsWith("cpython-3.11.") &&
      entry.name.includes(`-${target}-install_only`) &&
      entry.name.endsWith(".tar.gz")
    ) {
      return join(pythonStandaloneDir, entry.name);
    }
  }

  console.log("Downloading python-build-standalone...");
  const filename = `cpython-${PYTHON_STANDALONE_VERSION}-${target}-install_only.tar.gz`;
  const tarball = join(pythonStandaloneDir, filename);
  const downloadUrl = `https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_STANDALONE_RELEASE}/${
    encodeURIComponent(filename)
  }`;
  const curl = Deno.build.os === "windows" ? "curl.exe" : "/usr/bin/curl";
  await run(curl, ["-fL", "--retry", "5", "--retry-delay", "2", "-o", tarball, downloadUrl]);
  return tarball;
}

async function findWindowsSitePackages(outputDir: string): Promise<string> {
  const candidates = [
    join(outputDir, "python", "Lib", "site-packages"),
    join(outputDir, "python", "lib", "python3.11", "site-packages"),
  ];
  for (const candidate of candidates) {
    if (await pathExists(candidate)) return candidate;
  }
  throw new Error(`Could not find site-packages under ${outputDir}`);
}

async function verifyPortableRuntimeSurface(outputDir: string): Promise<void> {
  if (Deno.env.get("STIMMA_ALLOW_RESTRICTED_CODECS") === "1") {
    console.log("Runtime surface guard disabled (STIMMA_ALLOW_RESTRICTED_CODECS=1)");
    return;
  }

  const banned = [
    /^avcodec.*\.dll$/i,
    /^avformat.*\.dll$/i,
    /^avdevice.*\.dll$/i,
    /^avfilter.*\.dll$/i,
    /^x264.*\.dll$/i,
    /^x265.*\.dll$/i,
    /^vpx.*\.dll$/i,
    /^SvtAv1Enc.*\.dll$/i,
    /^rav1e.*\.dll$/i,
    /^bluray.*\.dll$/i,
    /^theora.*\.dll$/i,
  ];
  const hits: string[] = [];

  await removeMatching(outputDir, (_path, entry) => {
    const name = entry.name;
    if (entry.isDirectory && name.toLowerCase() === "cv2") {
      hits.push(name);
      return false;
    }
    if (entry.isFile && (name.toLowerCase().startsWith("cv2") && name.toLowerCase().endsWith(".pyd"))) {
      hits.push(name);
      return false;
    }
    if (entry.isFile && banned.some((re) => re.test(name))) {
      hits.push(name);
      return false;
    }
    return false;
  });

  if (hits.length > 0) {
    console.error("ERROR: runtime bundle includes disallowed media/codec artifacts:");
    for (const hit of [...new Set(hits)].sort()) console.error(`  ${hit}`);
    console.error("Set STIMMA_ALLOW_RESTRICTED_CODECS=1 only for temporary debugging builds.");
    Deno.exit(1);
  }

  console.log("Runtime surface check passed: no banned codec/cv2 artifacts found.");
}

async function buildWindowsPortableBackend(target: string): Promise<void> {
  const backendSrc = join(repoRoot, "backend");
  const pythonStandalone = join(repoRoot, "python-standalone");
  const outputDir = join(repoRoot, "src-tauri", "binaries", `stimma-backend-${target}`);
  const buildRoot = join(repoRoot, "build-experimental", `portable-backend-${target}`);
  const stagingDir = join(buildRoot, "staging");

  console.log("=== Portable Backend Build ===");
  console.log(`Target: ${target}`);
  console.log(`Output: ${outputDir}`);

  const tarball = await downloadWindowsStandalonePython(target, pythonStandalone);
  console.log(`Using Python: ${tarball}`);

  console.log("Cleaning output and staging directories...");
  await Deno.remove(outputDir, { recursive: true }).catch(() => {});
  await Deno.remove(stagingDir, { recursive: true }).catch(() => {});
  await Deno.mkdir(outputDir, { recursive: true });
  await Deno.mkdir(stagingDir, { recursive: true });

  console.log("Extracting portable Python...");
  await run("tar", ["-xzf", tarball, "-C", outputDir]);
  const pythonExe = join(outputDir, "python", "python.exe");
  if (!await pathExists(pythonExe)) {
    throw new Error(`Portable Python executable not found: ${pythonExe}`);
  }

  console.log("Exporting backend runtime requirements...");
  const requirements = await runCapture("uv", ["export", "--no-hashes", "--no-dev", "--no-emit-project"], { cwd: backendSrc });
  if (requirements.code !== 0) {
    console.error(requirements.stderr);
    Deno.exit(requirements.code);
  }
  await Deno.writeTextFile(join(outputDir, "requirements.txt"), requirements.stdout);

  console.log("Installing backend dependencies into portable Python...");
  await run("uv", ["pip", "install", "--python", pythonExe, "-r", join(outputDir, "requirements.txt")]);

  const sitePackages = await findWindowsSitePackages(outputDir);
  console.log("Pruning cv2 and bundled codec libraries from portable Python...");
  await Deno.remove(join(sitePackages, "cv2"), { recursive: true }).catch(() => {});
  await removeMatching(sitePackages, (_path, entry) => {
    const name = entry.name.toLowerCase();
    return name.startsWith("opencv_python_headless") || name.startsWith("opencv_python-");
  });
  await removeDirsByName(sitePackages, new Set(["__pycache__", "tests", "test"]));
  for (const name of ["pip", "setuptools", "wheel"]) {
    await Deno.remove(join(sitePackages, name), { recursive: true }).catch(() => {});
  }
  await removeMatching(sitePackages, (_path, entry) => {
    const name = entry.name.toLowerCase();
    return entry.isDirectory && (
      name.startsWith("pip-") ||
      name.startsWith("setuptools-") ||
      name.startsWith("wheel-")
    ) && name.endsWith(".dist-info");
  });

  console.log("Copying backend source...");
  const excludeDirs = new Set([
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".claude",
    "output",
    "tests",
    "tests_transition",
  ]);
  await copyDirFiltered(backendSrc, join(stagingDir, "backend"), (relativePath, entry) => {
    const normalized = relativePath.replaceAll("\\", "/");
    if (entry.isDirectory && excludeDirs.has(normalized)) return true;
    if (entry.isDirectory && normalized.endsWith(".egg-info")) return true;
    if (entry.isFile) {
      return normalized.endsWith(".pyc") ||
        normalized.endsWith(".spec") ||
        normalized.endsWith(".db") ||
        normalized === "pyproject.toml" ||
        normalized === "uv.lock" ||
        normalized.endsWith("-crash-report.xml");
    }
    return false;
  });
  await copyDir(join(stagingDir, "backend"), join(outputDir, "backend"));

  console.log("Copying app-level runtime files...");
  await Deno.copyFile(join(repoRoot, "prompts.yaml"), join(outputDir, "prompts.yaml"));

  console.log("Creating launchers...");
  // Build distribution baked into the launchers: 'dev' (default) or
  // 'official' (set only by release CI). Runtime env still wins so the
  // Tauri shell's compile-time value can override.
  const distribution = Deno.env.get("STIMMA_DISTRIBUTION") === "official" ? "official" : "dev";
  console.log(`Baking STIMMA_DISTRIBUTION=${distribution} into launchers...`);
  const runCmd = `@echo off\r\nsetlocal\r\nset PYTHONUTF8=1\r\nset PYTHONPATH=%~dp0;%~dp0backend;%PYTHONPATH%\r\nif not defined STIMMA_DISTRIBUTION set STIMMA_DISTRIBUTION=${distribution}\r\n"%~dp0python\\python.exe" "%~dp0backend\\main.py" %*\r\n`;
  const runSh = `#!/bin/bash\nDIR="$(cd "$(dirname "$0")" && pwd)"\nexport PYTHONUTF8=1\nexport PYTHONPATH="$DIR:$DIR/backend\${PYTHONPATH:+:$PYTHONPATH}"\nexport STIMMA_DISTRIBUTION="\${STIMMA_DISTRIBUTION:-${distribution}}"\nexec "$DIR/python/python.exe" "$DIR/backend/main.py" "$@"\n`;
  await Deno.writeTextFile(join(outputDir, "run.cmd"), runCmd);
  await Deno.writeTextFile(join(outputDir, "run.sh"), runSh);

  await verifyPortableRuntimeSurface(outputDir);

  const size = await dirSize(outputDir);
  console.log("");
  console.log("Portable backend build complete.");
  console.log(`Output: ${outputDir}`);
  console.log(`Backend payload: ${size.files} files, ${(size.bytes / 1024 / 1024).toFixed(1)}MB`);
}

async function buildPortableBackend(target: string): Promise<void> {
  if (Deno.build.os === "windows") {
    await buildWindowsPortableBackend(target);
    return;
  }
  await run("bash", [join(repoRoot, "scripts", "build-portable-backend.sh")], { cwd: repoRoot });
}

async function ensurePlatformResourceMapping(target: string): Promise<void> {
  if (Deno.build.os !== "windows" && Deno.build.os !== "linux") return;
  const tauriPath = join(repoRoot, "src-tauri", "tauri.conf.json");
  const raw = await Deno.readTextFile(tauriPath);
  const cfg = JSON.parse(raw);
  cfg.bundle.resources = {
    [`binaries/stimma-backend-${target}`]: "stimma-backend",
  };
  await Deno.writeTextFile(tauriPath, JSON.stringify(cfg, null, 2) + "\n");
}

async function getTauriProductName(): Promise<string> {
  const tauriPath = join(repoRoot, "src-tauri", "tauri.conf.json");
  const raw = await Deno.readTextFile(tauriPath);
  const cfg = JSON.parse(raw);
  return typeof cfg.productName === "string" && cfg.productName.trim() ? cfg.productName : "Stimma";
}

async function macosAppBundlePath(): Promise<string> {
  return join(
    repoRoot,
    "src-tauri",
    "target",
    "release",
    "bundle",
    "macos",
    `${await getTauriProductName()}.app`,
  );
}

async function linuxPythonVendoredLibPath(target: string): Promise<string | undefined> {
  if (Deno.build.os !== "linux") return undefined;

  const sitePackages = join(
    repoRoot,
    "src-tauri",
    "binaries",
    `stimma-backend-${target}`,
    "python",
    "lib",
    "python3.11",
    "site-packages",
  );
  if (!await pathExists(sitePackages)) return undefined;

  const dirs: string[] = [];
  for await (const entry of Deno.readDir(sitePackages)) {
    if (entry.isDirectory && entry.name.endsWith(".libs")) {
      dirs.push(join(sitePackages, entry.name));
    }
  }
  dirs.sort();
  return dirs.length > 0 ? dirs.join(":") : undefined;
}

async function appBuild(args: string[]): Promise<void> {
  let polishedDmg = false;

  for (const arg of args) {
    if (arg === "--release") polishedDmg = true;
    else {
      console.error(`Unknown flag for app build: ${arg}`);
      Deno.exit(1);
    }
  }

  const target = await detectTargetTriple();

  console.log("Building portable backend");
  await buildPortableBackend(target);

  await buildWatchdog(target);
  await ensurePlatformResourceMapping(target);

  const env: Record<string, string> = {};
  if (Deno.build.os === "darwin" && !polishedDmg) {
    env.CI = "true";
  }
  const linuxVendoredLibPath = await linuxPythonVendoredLibPath(target);
  if (linuxVendoredLibPath) {
    const inherited = Deno.env.get("LD_LIBRARY_PATH");
    env.LD_LIBRARY_PATH = inherited ? `${linuxVendoredLibPath}:${inherited}` : linuxVendoredLibPath;
  }

  const tauriCli = join(
    repoRoot,
    "frontend",
    "node_modules",
    ".bin",
    Deno.build.os === "windows" ? "tauri.cmd" : "tauri",
  );
  let tauriCommand = tauriCli;
  let tauriBuildArgs = ["build"];
  let tauriCwd = join(repoRoot, "src-tauri");
  if (!await pathExists(tauriCli)) {
    tauriCommand = "cargo";
    tauriBuildArgs = ["tauri", "build"];
  } else {
    tauriBuildArgs.push(
      "--config",
      JSON.stringify({
        build: {
          beforeBuildCommand: `npm --prefix ${join(repoRoot, "frontend")} run build`,
          frontendDist: "../frontend/dist",
        },
      }),
    );
  }
  if (Deno.build.os === "darwin" && Deno.env.get("APPLE_SIGNING_IDENTITY") && Deno.env.get("SKIP_NOTARIZE_WAIT") === "1") {
    tauriBuildArgs.push("--skip-stapling");
  }
  await run(tauriCommand, tauriBuildArgs, { cwd: tauriCwd, env });

  if (Deno.build.os === "darwin") {
    const appBundle = await macosAppBundlePath();
    if (await pathExists(appBundle)) {
      const verifyCode = await run("codesign", ["--verify", "--deep", "--strict", appBundle], {
        check: false,
      });
      if (verifyCode !== 0) {
        await run("codesign", ["--force", "--deep", "--sign", "-", appBundle]);
        await run("codesign", ["--verify", "--deep", "--strict", appBundle]);
      }
    }
  }
}

async function killPort(port: string): Promise<void> {
  try {
    const cmd = new Deno.Command("lsof", { args: ["-ti", `:${port}`], stdout: "piped", stderr: "null" });
    const out = await cmd.output();
    if (out.success) {
      const pids = new TextDecoder().decode(out.stdout).trim().split("\n").filter(Boolean);
      for (const pid of pids) {
        try { Deno.kill(Number(pid), "SIGKILL"); } catch { /* already dead */ }
      }
      if (pids.length > 0) {
        await new Promise((r) => setTimeout(r, 500));
      }
    }
  } catch { /* lsof not available or no processes */ }
}

async function waitForHttp(url: string, timeoutMs = 30000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(url);
      if (resp.ok || resp.status < 500) return;
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function resetAcceptanceSandbox(bundleId: string, sandbox: string): Promise<void> {
  const dataDir = getDataDir(bundleId, sandbox);
  const cacheDir = getCacheDir(bundleId, sandbox);
  for (const dir of [dataDir, cacheDir]) {
    try {
      await Deno.remove(dir, { recursive: true });
    } catch (err) {
      if (!(err instanceof Deno.errors.NotFound)) throw err;
    }
  }
}

async function writeAcceptanceConfig(bundleId: string, sandbox: string, backendPort: string): Promise<void> {
  const dataDir = getDataDir(bundleId, sandbox);
  const libraryDir = join(dataDir, "library");
  await Deno.mkdir(libraryDir, { recursive: true });

  const q = (value: string) => JSON.stringify(value);
  const config = `# Stimma acceptance-test configuration.
# Generated by \`stimma test acceptance\`; safe to delete with the sandbox.

profiles:
  - id: profile-acceptance
    name: "Acceptance"
    folders:
      - path: ${q(libraryDir)}
        allow_generate: true
        is_uploads_folder: true
        uploads_subfolder: "uploads"
    markers:
      - name: favorite
        icon_svg: heroicons:heart
        color: "#ef4444"
      - name: library
        icon_svg: heroicons:bookmark
        color: "#3b82f6"

tool_providers: []
generators: []

default_model: auto

cloud:
  # Unroutable on purpose: the lane must be hermetic. Marketplace
  # auto-install/check-updates/update fail fast instead of reaching
  # stimma.ai — a slow real download can wedge the backend mid-test.
  base_url: "http://127.0.0.1:1"

llms:
  # A configured (not live) endpoint keeps the app-entry readiness gate
  # satisfied — the lane's fake tool provider covers generation, and no
  # acceptance test exercises the agent LLM itself.
  agent:
    source: auto
    endpoint:
      url: "http://127.0.0.1:1/acceptance-fake"
      model: "acceptance-fake"
  agent-fast:
    source: auto

clip:
  model: "ViT-g-14"
  pretrained: "laion2b_s12b_b42k"

face_detection:
  enabled: true
  min_confidence: 0.5
  max_faces: 10
  parallelism: 2

telemetry:
  enabled: false

server:
  host: "127.0.0.1"
  port: ${backendPort}
  log_level: INFO
`;

  await Deno.mkdir(dataDir, { recursive: true });
  await Deno.writeTextFile(join(dataDir, "config.yaml"), config);
}

async function resetAcceptanceArtifacts(): Promise<void> {
  for (const path of [
    join(repoRoot, "frontend", "test-results"),
    join(repoRoot, "frontend", "acceptance", ".auth"),
    join(repoRoot, "frontend", "acceptance", "playwright-report"),
    join(repoRoot, "frontend", "acceptance", "acceptance"),
  ]) {
    try {
      await Deno.remove(path, { recursive: true });
    } catch (err) {
      if (!(err instanceof Deno.errors.NotFound)) throw err;
    }
  }
}

async function testAcceptance(args: string[]): Promise<void> {
  const backendPort = "19291";
  const frontendPort = "19292";
  const bundleId = "ai.stimma.stimma.acceptance-test";
  const sandbox = "default";

  const noServer = args.includes("--no-server");
  const noReset = args.includes("--no-reset");
  const verbose = args.includes("--verbose");
  let slowMo: string | null = null;
  const filteredArgs: string[] = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (["--verbose", "--no-server", "--no-reset"].includes(arg)) continue;
    if (arg === "--slow-mo") {
      slowMo = args[i + 1] || null;
      i += 1;
      continue;
    }
    if (arg.startsWith("--slow-mo=")) {
      slowMo = arg.slice("--slow-mo=".length);
      continue;
    }
    filteredArgs.push(arg);
  }
  const stdio = verbose ? "inherit" as const : "null" as const;

  const env = {
    STIMMA_TEST_PROVIDER: "1",
    STIMMA_BACKEND_PORT: backendPort,
    STIMMA_FRONTEND_PORT: frontendPort,
    STIMMA_ACCEPTANCE_BACKEND_URL: `http://localhost:${backendPort}`,
    ...(slowMo ? { STIMMA_ACCEPTANCE_SLOW_MO: slowMo } : {}),
  };

  let backend: Deno.ChildProcess | null = null;
  let frontend: Deno.ChildProcess | null = null;

  if (!noServer) {
    await killPort(backendPort);
    await killPort(frontendPort);

    if (!noReset) {
      console.log(`Resetting acceptance sandbox (bundle=${bundleId}, sandbox=${sandbox})...`);
      await resetAcceptanceSandbox(bundleId, sandbox);
      await writeAcceptanceConfig(bundleId, sandbox, backendPort);
    } else {
      const configPath = join(getDataDir(bundleId, sandbox), "config.yaml");
      try {
        const configText = await Deno.readTextFile(configPath);
        if (configText.includes("/Documents/Stimma") || configText.includes("\\Documents\\Stimma")) {
          console.error(
            "The existing acceptance config points at Documents/Stimma. " +
            "Run `stimma test acceptance` without --no-reset once to recreate the isolated sandbox.",
          );
          Deno.exit(1);
        }
      } catch (err) {
        if (!(err instanceof Deno.errors.NotFound)) throw err;
        await writeAcceptanceConfig(bundleId, sandbox, backendPort);
      }
    }

    console.log(`Starting acceptance backend on :${backendPort} (bundle=${bundleId})...`);
    const backendCmd = new Deno.Command("uv", {
      args: ["run", "python", "main.py", `--bundle-id=${bundleId}`, `--sandbox=${sandbox}`, `--port=${backendPort}`],
      cwd: join(repoRoot, "backend"),
      env: { ...Deno.env.toObject(), ...env },
      stdin: "null",
      stdout: stdio,
      stderr: stdio,
    });
    backend = backendCmd.spawn();

    console.log(`Starting acceptance frontend on :${frontendPort}...`);
    const frontendCmd = new Deno.Command("npx", {
      args: ["vite"],
      cwd: join(repoRoot, "frontend"),
      env: { ...Deno.env.toObject(), ...env },
      stdin: "null",
      stdout: stdio,
      stderr: stdio,
    });
    frontend = frontendCmd.spawn();
  }

  let testCode = 1;
  try {
    console.log("Waiting for acceptance backend...");
    await waitForHttp(`http://localhost:${backendPort}/api/profiles`);
    console.log("Waiting for acceptance frontend...");
    await waitForHttp(`http://localhost:${frontendPort}/`);
    console.log("Servers ready. Running acceptance tests...\n");
    await resetAcceptanceArtifacts();

    const pw = ["playwright", "test", "--config", "acceptance/playwright.config.ts", ...filteredArgs];
    const testCmd = new Deno.Command("npx", {
      args: pw,
      cwd: join(repoRoot, "frontend"),
      env: { ...Deno.env.toObject(), ...env },
      stdin: "inherit",
      stdout: "inherit",
      stderr: "inherit",
    });
    const testChild = testCmd.spawn();
    const testResult = await testChild.status;
    testCode = testResult.code;
  } finally {
    if (!noServer) {
      console.log("\nShutting down acceptance servers...");
      try { frontend?.kill("SIGTERM"); } catch { /* already dead */ }
      try { backend?.kill("SIGTERM"); } catch { /* already dead */ }
      const waits: Promise<unknown>[] = [];
      if (frontend) waits.push(frontend.status);
      if (backend) waits.push(backend.status);
      await Promise.allSettled(waits);
    }
  }

  if (testCode !== 0) {
    Deno.exit(testCode);
  }
}

const DEV_STIMPACKS_KEY = "dev_stimpacks_dir";
const DEV_STIMPACKS_LINE_RE = /^dev_stimpacks_dir:.*$/m;

async function commandStimpacks(args: string[], bundleId: string, sandbox: string): Promise<void> {
  const sub = args[0];

  if (sub === "validate") {
    const targets = args.slice(1).filter((a) => !a.startsWith("--"));
    if (targets.length === 0) {
      console.error("Usage: stimma stimpacks validate <path> [<path> ...]");
      Deno.exit(1);
    }
    const abs = targets.map((t) => resolve(t));
    const code = await run(
      "uv",
      ["run", "python", "-m", "agent.v2.stimpack_validate", ...abs],
      { cwd: join(repoRoot, "backend"), check: false },
    );
    Deno.exit(code);
  }

  if (sub !== "dev") {
    console.error(
      "Usage: stimma stimpacks dev [path]      Set dev stimpacks override (default: sibling stimma-skills)\n" +
      "       stimma stimpacks dev --off       Clear the dev stimpacks override\n" +
      "       stimma stimpacks validate <path> Validate a stimpack directory with the real loader",
    );
    Deno.exit(1);
  }

  const configPath = join(getDataDir(bundleId, sandbox), "config.yaml");
  let text: string;
  try {
    text = await Deno.readTextFile(configPath);
  } catch {
    console.error(
      `Config file not found: ${configPath}\n` +
      `Start the app for this channel/sandbox once so it creates config.yaml, then retry.`,
    );
    Deno.exit(1);
  }

  // Narrow, line-level edit (preserve comments/formatting); back up first.
  await Deno.writeTextFile(`${configPath}.bak`, text);

  if (args[1] === "--off") {
    if (!DEV_STIMPACKS_LINE_RE.test(text)) {
      console.log("Dev stimpacks override is not set; nothing to do.");
      return;
    }
    await Deno.writeTextFile(configPath, text.replace(/^dev_stimpacks_dir:.*\n?/m, ""));
    console.log(`Cleared dev stimpacks override in ${configPath} (backup: ${configPath}.bak).`);
    console.log("Backend reverts to profile-installed stimpacks on next config reload.");
    return;
  }

  const raw = args[1] && !args[1].startsWith("--") ? args[1] : join(repoRoot, "..", "stimma-skills");
  const abs = resolve(raw);
  if (!(await pathExists(abs))) {
    console.error(`Stimpacks directory not found: ${abs}`);
    Deno.exit(1);
  }

  const line = `${DEV_STIMPACKS_KEY}: ${JSON.stringify(abs)}`;
  const next = DEV_STIMPACKS_LINE_RE.test(text)
    ? text.replace(DEV_STIMPACKS_LINE_RE, line)
    : text.replace(/\s*$/, "") + "\n" + line + "\n";
  await Deno.writeTextFile(configPath, next);

  console.log(`Dev stimpacks override set: ${abs}`);
  console.log(`Wrote ${configPath} (backup: ${configPath}.bak).`);
  console.log("These stimpacks now shadow profile-installed built-ins; backend picks it up on config reload.");
}

// app_branch the backend's User-Agent reports for a bundle id when the
// distribution is official (mirrors backend/user_agent.py get_app_branch).
function appBranchForBundle(bundleId: string): string {
  if (bundleId === "ai.stimma.stimma") return "production";
  if (bundleId === "ai.stimma.stimma.beta") return "beta";
  if (bundleId === "ai.stimma.stimma.canary") return "canary";
  return "dev";
}

function officialBanner(bundleId: string): void {
  console.log(
    `⚠ STIMMA_DISTRIBUTION=official — telemetry/consent/thumbs/crash surfaces ACTIVE; ` +
      `events will be sent to the configured cloud (app_branch will be '${appBranchForBundle(bundleId)}')`,
  );
}

function tauriTargetDir(sandbox: string): string | undefined {
  if (sandbox === "default") return undefined;
  return join(repoRoot, "target-tauri", sandboxSafeSegment(sandbox));
}

function tauriDevEnv(bundleId: string, ports: { server: number; frontend: number }, sandbox: string, runtimeEnv: Record<string, string>): Record<string, string> {
  const targetDir = tauriTargetDir(sandbox);
  const env: Record<string, string> = {
    ...runtimeEnv,
    STIMMA_DEV: "1",
    STIMMA_BACKEND_PORT: String(ports.server),
    STIMMA_FRONTEND_PORT: String(ports.frontend),
    STIMMA_SANDBOX: sandbox,
    STIMMA_DATA_DIR: getDataDir(bundleId, sandbox),
    STIMMA_CACHE_DIR: getCacheDir(bundleId, sandbox),
  };
  if (targetDir) env.CARGO_TARGET_DIR = targetDir;
  return env;
}

function tauriDevConfig(bundleId: string, sandbox: string, ports: { frontend: number }): string {
  return JSON.stringify({
    identifier: sandboxIdentifier(bundleId, sandbox),
    build: {
      devUrl: `http://${DEV_HOST}:${ports.frontend}`,
    },
  });
}

async function commandDevAll(bundleId: string, sandbox: string, runtimeEnv: Record<string, string>): Promise<void> {
  const ports = await getSandboxPorts(bundleId, sandbox);
  const backendDir = join(repoRoot, "backend");
  const frontendDir = join(repoRoot, "frontend");
  const backendExec = `uv run python main.py --bundle-id=${bundleId} --sandbox=${sandbox} --port=${ports.server}`;
  const backendArgs = Deno.build.os === "windows"
    ? ["nodemon", "--signal", "SIGKILL", "--exec", backendExec]
    : ["nodemon", "--signal", "SIGKILL", "--exec", backendExec];
  const portEnv = {
    STIMMA_BACKEND_PORT: String(ports.server),
    STIMMA_FRONTEND_PORT: String(ports.frontend),
  };
  const tauriConfig = tauriDevConfig(bundleId, sandbox, ports);
  const processes: DevProcess[] = [];
  let shuttingDown = false;
  let shutdownPromise: Promise<void> | null = null;

  const shutdown = (exitCode?: number) => {
    if (shutdownPromise) return shutdownPromise;
    shuttingDown = true;
    shutdownPromise = (async () => {
      const hadStartedProcesses = processes.length > 0;
      await terminateDevProcesses(processes);
      if (hadStartedProcesses) {
        await Promise.all([
          warnIfTcpPortStillOpen(ports.server, "backend"),
          warnIfTcpPortStillOpen(ports.frontend, "frontend"),
        ]);
      }
      if (exitCode !== undefined) Deno.exit(exitCode);
    })();
    return shutdownPromise;
  };

  const handleSigint = () => {
    console.log("\n[dev all] Received Ctrl-C; stopping dev stack...");
    void shutdown(130);
  };
  const handleSigterm = () => {
    console.log("\n[dev all] Received SIGTERM; stopping dev stack...");
    void shutdown(143);
  };

  Deno.addSignalListener("SIGINT", handleSigint);
  Deno.addSignalListener("SIGTERM", handleSigterm);

  console.log(`Starting Stimma dev stack (bundle=${bundleId}, sandbox=${sandbox}, backend=:${ports.server}, frontend=:${ports.frontend})`);
  if (runtimeEnv.STIMMA_DISTRIBUTION === "official") {
    console.log("Official distribution mode is active for backend, frontend, and app.");
  }

  try {
    await Promise.all([
      assertTcpPortAvailable(ports.server, "backend"),
      assertTcpPortAvailable(ports.frontend, "frontend"),
    ]);

    processes.push(spawnDevProcess("backend", "npx", backendArgs, { cwd: backendDir, env: runtimeEnv }));
    processes.push(spawnDevProcess("frontend", "npm", VITE_DEV_ARGS, { cwd: frontendDir, env: { ...runtimeEnv, ...portEnv } }));

    console.log("[dev all] Waiting up to 10 minutes for backend startup; one-time profile migrations report progress below.");
    await waitForReadyOrExit(processes, Promise.all([
      waitForTcpPort(ports.server, "backend", 10 * 60 * 1000, [DEV_HOST]),
      waitForTcpPort(ports.frontend, "frontend", 60000, [DEV_HOST]),
    ]).then(() => undefined));

    console.log("[dev all] Backend and frontend are ready; launching Tauri app.");
    processes.push(spawnDevProcess("app", "cargo", ["tauri", "dev", "--config", tauriConfig], {
      cwd: repoRoot,
      env: tauriDevEnv(bundleId, ports, sandbox, runtimeEnv),
    }));
    console.log("[dev all] App process started. Press Ctrl-C to stop the full stack.");

    const firstExit = await Promise.race(processes.map(async (proc) => ({ proc, status: await proc.status })));
    if (!shuttingDown) {
      console.log(`[dev all] ${firstExit.proc.label} exited with code ${firstExit.status.code}; stopping remaining processes.`);
      await shutdown();
      Deno.exit(firstExit.status.code);
    }
    await shutdownPromise;
  } catch (err) {
    console.error(`[dev all] ${err}`);
    await shutdown();
    Deno.exit(1);
  } finally {
    try {
      Deno.removeSignalListener("SIGINT", handleSigint);
      Deno.removeSignalListener("SIGTERM", handleSigterm);
    } catch {
      // Ignore cleanup failures while exiting.
    }
  }
}

async function main(): Promise<void> {
  let args = [...Deno.args];
  let channel = "debug";
  let sandbox = "default";
  let official = false;

  while (args.length > 0) {
    if (args[0] === "--prod") {
      channel = "production";
      args = args.slice(1);
      continue;
    }
    if (args[0] === "--channel" || args[0].startsWith("--channel=")) {
      const value = args[0] === "--channel" ? args[1] : args[0].slice("--channel=".length);
      if (!value) {
        console.error("--channel requires a value.");
        Deno.exit(1);
      }
      channel = value;
      if (!(channel in CHANNEL_BUNDLE_IDS)) {
        console.error(`Unknown channel: ${channel}. Valid: ${Object.keys(CHANNEL_BUNDLE_IDS).join(", ")}`);
        Deno.exit(1);
      }
      args = args.slice(args[0] === "--channel" ? 2 : 1);
      continue;
    }
    if (args[0] === "--sandbox" || args[0].startsWith("--sandbox=")) {
      const value = args[0] === "--sandbox" ? args[1] : args[0].slice("--sandbox=".length);
      if (!value) {
        console.error("--sandbox requires a value.");
        Deno.exit(1);
      }
      sandbox = value;
      args = args.slice(args[0] === "--sandbox" ? 2 : 1);
      continue;
    }
    if (args[0] === "--official") {
      official = true;
      args = args.slice(1);
      continue;
    }
    break;
  }

  // Also accept --official after the subcommand (e.g. `stimma dev backend --official`).
  if (args.includes("--official")) {
    official = true;
    args = args.filter((a) => a !== "--official");
  }

  const bundleId = CHANNEL_BUNDLE_IDS[channel];

  if (official) {
    const command0 = args[0];
    if (command0 !== "dev" && command0 !== "run") {
      console.error("--official is only supported with 'stimma dev ...' and 'stimma run ...'.");
      Deno.exit(1);
    }
    officialBanner(bundleId);
  }
  // Env merged into child processes when --official is set. Empty otherwise,
  // so the default dev behavior is completely untouched.
  const officialEnv: Record<string, string> = official ? { STIMMA_DISTRIBUTION: "official" } : {};

  const command = args[0];
  if (!command) printUsage();

  const localEnv = command === "dev" || command === "run" ? await loadLocalEnvOverrides() : {};
  if (Object.keys(localEnv).length > 0) {
    console.log(`Loaded ${LOCAL_ENV_FILENAME}: ${summarizeEnvOverrides(localEnv)}`);
  }
  const runtimeEnv: Record<string, string> = { ...localEnv, ...officialEnv };

  const sub = args[1];
  const rest = args.slice(2);

  switch (command) {
    case "dev": {
      if (sub === "frontend") {
        // Pass sandbox ports so forked sandboxes get their own Vite port and
        // proxy to their own backend (vite.config.js reads these; defaults
        // are 9191/9192, so the default sandbox is unchanged).
        const ports = await getSandboxPorts(bundleId, sandbox);
        const portEnv = {
          STIMMA_BACKEND_PORT: String(ports.server),
          STIMMA_FRONTEND_PORT: String(ports.frontend),
        };
        await run("npm", VITE_DEV_ARGS, { cwd: join(repoRoot, "frontend"), env: { ...runtimeEnv, ...portEnv } });
      } else if (sub === "backend") {
        const backendDir = join(repoRoot, "backend");
        const ports = await getSandboxPorts(bundleId, sandbox);
        const execStr = `uv run python main.py --bundle-id=${bundleId} --sandbox=${sandbox} --port=${ports.server}`;
        if (Deno.build.os === "windows") {
          const cmdArgs = ["nodemon", "--signal", "SIGKILL", "--exec", execStr];
          await run("npx", cmdArgs, { cwd: backendDir, env: runtimeEnv });
        } else {
          await run("npx", ["nodemon", "--signal", "SIGKILL", "--exec", execStr], { cwd: backendDir, env: runtimeEnv });
        }
      } else if (sub === "backend2") {
        const ports = await getSandboxPorts(bundleId, sandbox);
        const args2 = ["run", "--", "--bundle-id", bundleId, "--sandbox", sandbox, "--port", String(ports.server), "--console"];
        await run("cargo", args2, { cwd: join(repoRoot, "backend2"), env: runtimeEnv });
      } else if (sub === "app") {
        const ports = await getSandboxPorts(bundleId, sandbox);
        if (official) {
          console.log(`Note: 'dev app' uses the externally running backend on :${ports.server} — start it with 'stimma dev backend --official' for backend surfaces.`);
        }
        await run("cargo", ["tauri", "dev", "--config", tauriDevConfig(bundleId, sandbox, ports)], {
          cwd: repoRoot,
          env: tauriDevEnv(bundleId, ports, sandbox, runtimeEnv),
        });
      } else if (sub === "all") {
        await commandDevAll(bundleId, sandbox, runtimeEnv);
      } else {
        printUsage();
      }
      break;
    }

    case "tail": {
      const dataDir = getDataDir(bundleId, sandbox);
      const backendLog = join(dataDir, "Logs", "Stimma_log.00.txt");
      const tauriLog = Deno.build.os === "darwin"
        ? join(Deno.env.get("HOME") || "", "Library", "Logs", "com.stimma.app", "Stimma.log")
        : join(dataDir, "Logs", "Stimma.log");

      if (sub === "backend") {
        if (Deno.build.os === "windows") {
          await run("powershell", ["-NoProfile", "-Command", `Get-Content -Path '${backendLog}' -Wait -Tail 1000`]);
        } else {
          await run("tail", ["-f", "-n", "1000", backendLog]);
        }
      } else if (sub === "app") {
        if (Deno.build.os === "windows") {
          await run("powershell", ["-NoProfile", "-Command", `Get-Content -Path '${tauriLog}' -Wait -Tail 1000`]);
        } else {
          await run("tail", ["-f", "-n", "1000", tauriLog]);
        }
      } else {
        printUsage();
      }
      break;
    }

    case "app": {
      if (sub === "build") {
        await appBuild(rest);
      } else if (sub === "run") {
        if (Deno.build.os === "darwin") {
          await run("open", [await macosAppBundlePath()]);
        } else if (Deno.build.os === "windows") {
          const exe = join(repoRoot, "src-tauri", "target", "release", "stimma.exe");
          await run(exe, []);
        } else {
          console.error("app run is not implemented for this OS");
          Deno.exit(1);
        }
      } else if (sub === "install") {
        if (Deno.build.os !== "darwin") {
          console.error("app install currently supports macOS only.");
          Deno.exit(1);
        }
        const appBundle = await macosAppBundlePath();
        if (!(await pathExists(appBundle))) {
          console.error("Error: App not built. Run 'stimma app build' first.");
          Deno.exit(1);
        }
        const installedBundle = join("/Applications", `${await getTauriProductName()}.app`);
        await run("rm", ["-rf", installedBundle]);
        await run("cp", ["-R", appBundle, installedBundle]);
      } else {
        printUsage();
      }
      break;
    }

    case "run": {
      if (sub === "backend") {
        const ports = await getSandboxPorts(bundleId, sandbox);
        const args2 = ["run", "python", "main.py", `--bundle-id=${bundleId}`, `--sandbox=${sandbox}`, `--port=${ports.server}`];
        await run("uv", args2, { cwd: join(repoRoot, "backend"), env: runtimeEnv });
      } else if (sub === "frontend") {
        const frontendDir = join(repoRoot, "frontend");
        await run("npm", ["run", "build"], { cwd: frontendDir, env: runtimeEnv });
        await run("npm", ["run", "preview"], { cwd: frontendDir, env: runtimeEnv });
      } else if (sub === "app") {
        if (official) {
          console.log("Note: 'run app' uses the externally running backend on :9191 — start it with 'stimma run backend --official' for backend surfaces.");
        }
        await run("cargo", ["run", "--release"], { cwd: repoRoot, env: { ...runtimeEnv, STIMMA_DEV: "1" } });
      } else {
        printUsage();
      }
      break;
    }

    case "config": {
      if (sub !== "edit") {
        printUsage();
      }
      const configPath = join(getDataDir(bundleId, sandbox), "config.yaml");
      if (!(await pathExists(configPath))) {
        console.error(`Config file not found: ${configPath}`);
        Deno.exit(1);
      }
      await run(Deno.env.get("EDITOR") || "vi", [configPath]);
      break;
    }

    case "backup": {
      const dataDir = getDataDir(bundleId, sandbox);
      if (!(await pathExists(dataDir))) {
        console.error(`Error: Data directory not found: ${dataDir}`);
        Deno.exit(1);
      }
      await requireSandboxBackendStopped(bundleId, sandbox, "snapshot");
      const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
      const backupDir = `${dataDir}-backup-${stamp}`;
      console.log(`Snapshotting ${dataDir} → ${backupDir}...`);
      await copyDataDirSnapshot(dataDir, backupDir);
      console.log(`Snapshot complete: ${backupDir}`);
      break;
    }

    case "lint": {
      if (sub === "backend" || !sub) {
        await run("uv", ["run", "ruff", "check", ".", ...rest], { cwd: join(repoRoot, "backend") });
      } else if (sub === "frontend-dead-code") {
        await run("npm", ["run", "lint:dead-code", "--", ...rest], { cwd: join(repoRoot, "frontend") });
      } else {
        printUsage();
      }
      break;
    }

    case "test": {
      if (sub === "backend") {
        await run("uv", ["run", "pytest", ...rest], { cwd: join(repoRoot, "backend") });
      } else if (sub === "acceptance") {
        await testAcceptance(rest);
      } else if (sub === "cv2-parity") {
        await run("uv", ["run", "--extra", "cv2-parity", "python", "tests_transition/prove_cv2_removal.py", ...rest], { cwd: join(repoRoot, "backend") });
      } else {
        printUsage();
      }
      break;
    }

    case "dir": {
      console.log(getDataDir(bundleId, sandbox));
      break;
    }

    case "oss":
    case "attribution": {
      // Regenerate the generated dependency tables in ATTRIBUTION.md from the
      // real lockfiles/metadata. Warnings mean a package's license couldn't be
      // resolved automatically — verify it upstream and add an override in the
      // script before shipping.
      await run("python3", [join(repoRoot, "scripts", "generate-attribution.py")], { cwd: repoRoot });
      await run("git", ["--no-pager", "diff", "--stat", "ATTRIBUTION.md"], { cwd: repoRoot });
      break;
    }

    case "doctor": {
      if (sub !== "assets") {
        printUsage();
      }
      await run(
        "uv",
        [
          "run",
          "python",
          "-m",
          "asset_doctor",
          "--data-dir",
          getDataDir(bundleId, sandbox),
          ...rest,
        ],
        { cwd: join(repoRoot, "backend") },
      );
      break;
    }

    case "migrate-to-managed-storage": {
      const applying = args.slice(1).includes("--apply");
      if (applying) {
        const ports = await getSandboxPorts(bundleId, sandbox);
        for (const hostname of LOCALHOSTS) {
          if (await isTcpPortOpen(hostname, ports.server, 200)) {
            console.error(
              `Refusing to migrate while the backend is listening on ${hostname}:${ports.server}. ` +
                "Stop Stimma for this sandbox first.",
            );
            Deno.exit(1);
          }
        }
      }
      await run(
        "uv",
        [
          "run",
          "python",
          "-m",
          "managed_storage_migration",
          "--data-dir",
          getDataDir(bundleId, sandbox),
          ...args.slice(1),
        ],
        { cwd: join(repoRoot, "backend") },
      );
      break;
    }

    case "rewrite": {
      if (sub !== "prompts") {
        printUsage();
      }
      const applying = rest.includes("--apply");
      if (applying) {
        const ports = await getSandboxPorts(bundleId, sandbox);
        for (const hostname of LOCALHOSTS) {
          if (await isTcpPortOpen(hostname, ports.server, 200)) {
            console.error(
              `Refusing to rewrite while the backend is listening on ${hostname}:${ports.server}. ` +
                "Stop Stimma for this sandbox first.",
            );
            Deno.exit(1);
          }
        }
      }
      await run(
        "uv",
        [
          "run",
          "python",
          "-m",
          "prompt_history_rewrite",
          "--data-dir",
          getDataDir(bundleId, sandbox),
          ...rest,
        ],
        { cwd: join(repoRoot, "backend") },
      );
      break;
    }

    case "fork": {
      if (!sub || sub === "list") {
        // List all sandboxes
        const root = getBundleDataRoot(bundleId);
        if (!(await pathExists(root))) {
          console.log("No sandboxes found.");
          break;
        }
        for await (const entry of Deno.readDir(root)) {
          if (!entry.isDirectory) continue;
          const sandboxDir = join(root, entry.name);
          let ports = "";
          const assignedPorts = await readSandboxPorts(bundleId, entry.name);
          if (assignedPorts) {
            ports = `  server=:${assignedPorts.server} frontend=:${assignedPorts.frontend}`;
          } else if (entry.name === "default") {
            ports = `  server=:${DEFAULT_BACKEND_PORT} frontend=:${DEFAULT_FRONTEND_PORT}`;
          }
          // Get directory size (rough)
          let sizeStr = "";
          try {
            const du = await runCapture("du", ["-sh", sandboxDir]);
            if (du.code === 0) {
              sizeStr = `  ${du.stdout.split(/\s/)[0].trim()}`;
            }
          } catch { /* ignore */ }
          console.log(`${entry.name}${sizeStr}${ports}`);
        }
      } else if (sub === "create") {
        const empty = rest.includes("--empty");
        const name = rest.find((a) => !a.startsWith("--"));
        if (!name) {
          console.error("Usage: stimma fork create NAME [--empty]");
          Deno.exit(1);
        }
        if (name === "default") {
          console.error("Cannot fork 'default' — it already exists.");
          Deno.exit(1);
        }
        const srcData = getDataDir(bundleId, "default");
        const dstData = getDataDir(bundleId, name);
        const dstCache = getCacheDir(bundleId, name);
        if (await pathExists(dstData)) {
          console.error(`Sandbox '${name}' already exists at: ${dstData}`);
          Deno.exit(1);
        }
        if (empty) {
          // Fresh first-run sandbox: data dir contains only .fork.json. The
          // backend auto-initializes config.yaml (consent undetermined, no
          // coachmark, no region cache) on first boot.
          console.log(`Creating empty sandbox at ${dstData}...`);
          await Deno.mkdir(dstData, { recursive: true });
        } else {
          if (!(await pathExists(srcData))) {
            console.error(`Default sandbox not found at: ${srcData}`);
            Deno.exit(1);
          }
          await requireSandboxBackendStopped(bundleId, "default", "fork");
          console.log(`Snapshotting ${srcData} → ${dstData}...`);
          await copyDataDirSnapshot(srcData, dstData);
        }
        await Deno.mkdir(dstCache, { recursive: true });
        const ports = await nextSandboxPorts(bundleId);
        await writeSandboxPorts(bundleId, name, ports);
        console.log(`Sandbox '${name}' created${empty ? " (empty, first-run)" : ""}.`);
        console.log(`  Server port:   ${ports.server}`);
        console.log(`  Frontend port: ${ports.frontend}`);
      } else if (sub === "destroy") {
        const yes = rest.includes("--yes") || rest.includes("-y");
        const name = rest.find((a) => !a.startsWith("-"));
        if (!name) {
          console.error("Usage: stimma fork destroy NAME [--yes]");
          Deno.exit(1);
        }
        if (name === "default") {
          console.error("Cannot destroy the default sandbox.");
          Deno.exit(1);
        }
        const dataDir = getDataDir(bundleId, name);
        const cacheDir = getCacheDir(bundleId, name);
        if (!(await pathExists(dataDir))) {
          console.error(`Sandbox '${name}' not found at: ${dataDir}`);
          Deno.exit(1);
        }
        if (!yes) {
          const answer = prompt(`Delete sandbox '${name}'? This removes all data. (y/N)`);
          if (answer?.toLowerCase() !== "y") {
            console.log("Aborted.");
            Deno.exit(0);
          }
        }
        if (await pathExists(dataDir)) await Deno.remove(dataDir, { recursive: true });
        if (await pathExists(cacheDir)) await Deno.remove(cacheDir, { recursive: true });
        console.log(`Sandbox '${name}' destroyed.`);
      } else {
        printUsage();
      }
      break;
    }

    case "bd": {
      await run("bd", args.slice(1));
      break;
    }

    case "stimpacks": {
      await commandStimpacks(args.slice(1), bundleId, sandbox);
      break;
    }

    case "tag": {
      await commandTag(args.slice(1));
      break;
    }

    case "promote": {
      await commandPromote(args.slice(1));
      break;
    }

    default:
      printUsage();
  }
}

main().catch((err) => {
  Deno.stderr.writeSync(encoder.encode(`${String(err)}\n`));
  Deno.exit(1);
});
