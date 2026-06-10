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
  alpha: "ai.stimma.stimma.alpha",
  beta: "ai.stimma.stimma.beta",
  production: "ai.stimma.stimma",
  // Backward-compatible aliases. New commands should use alpha/production.
  canary: "ai.stimma.stimma.alpha",
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

async function getSandboxPorts(bundleId: string, sandbox: string): Promise<{ server: number; frontend: number }> {
  // Check for .fork.json (written by `stimma fork create`) for port overrides
  const forkJson = join(getDataDir(bundleId, sandbox), ".fork.json");
  try {
    const data = JSON.parse(await Deno.readTextFile(forkJson));
    return { server: data.server_port, frontend: data.frontend_port };
  } catch {
    // No .fork.json — use default ports. This is fine for single-sandbox usage.
    // Only matters if running multiple sandboxes simultaneously.
    return { server: 9191, frontend: 9192 };
  }
}

function printUsage(): never {
  console.log(`Stimma Development CLI

Usage: stimma [FLAGS] <command> <subcommand>

Flags:
  --prod              Shorthand for --channel=production
  --channel=CHANNEL   Release channel: debug (default), sandbox, alpha, beta, production
  --sandbox=NAME      Sandbox name (default: "default")
  --official          dev/run only: set STIMMA_DISTRIBUTION=official in the child
                      process so telemetry, consent UI, thumbs, and crash reports
                      behave like an official build (events go to the configured
                      cloud; app_branch stays 'dev' on the debug channel)

Commands:
  dev frontend    Run Vite dev server with HMR (port 9192)
  dev backend     Run Python backend with nodemon (port 9191)
  dev backend2    Run Rust backend (port 9191)
  dev app         Run Tauri in dev mode
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
  skills dev [path]   Use a skills dir as the live authority for built-in skills
                      (default: sibling stimma-skills repo). Shadows installed copies.
  skills dev --off    Clear the dev skills override
  backup          Create timestamped backup of data directory
  test backend    Run backend pytest tests
  test frontend   Run frontend e2e tests (starts its own backend+frontend)
  test frontend --ui       Open Playwright UI mode
  test frontend --verbose  Show backend/frontend server logs
  test cv2-parity Run cv2 parity proof (uses optional cv2-parity extra)
  eval run        Run agent evals
  eval list       List available eval tasks
  eval results    Show recent eval runs
  tag alpha [X.Y.Z]   Create and push next alpha tag (or for explicit base version)
  tag beta [X.Y.Z]    Create and push next beta tag (or for explicit base version)
  tag production [X.Y.Z] Create and push production tag
  dir               Print data directory path
  fork              List all sandboxes with sizes and ports
  fork create NAME  Copy default sandbox to a new named sandbox
  fork create NAME --empty  Create a FRESH first-run sandbox (empty except
                      .fork.json with auto-assigned ports) — backend boots it
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

async function createAndPushTag(tagName: string): Promise<void> {
  if (await tagExists(tagName)) {
    console.error(`Tag already exists: ${tagName}`);
    Deno.exit(1);
  }
  // Annotated tag with a message — works regardless of the repo's
  // tag.gpgSign / forceSignAnnotated git config (a lightweight `git tag <name>`
  // fails with "no tag message?" when annotation is forced).
  await run("git", ["tag", "-a", tagName, "-m", `Release ${tagName}`], { cwd: repoRoot });
  await run("git", ["push", "origin", `refs/tags/${tagName}`], { cwd: repoRoot });
  console.log(`Tagged and pushed: ${tagName}`);
}

function nextAvailablePatch(core: SemverCore, existing: Set<string>): SemverCore {
  let candidate = core;
  while (existing.has(`v${fmtCore(candidate)}`)) {
    candidate = bumpPatch(candidate);
  }
  return candidate;
}

async function commandTag(args: string[]): Promise<void> {
  const mode = args[0];
  const explicit = args[1];

  if (!mode || (mode !== "alpha" && mode !== "beta" && mode !== "production")) {
    console.error("Usage: stimma tag {alpha|beta|production} [X.Y.Z]");
    Deno.exit(1);
  }

  if (args.length > 2) {
    console.error("Usage: stimma tag {alpha|beta|production} [X.Y.Z]");
    Deno.exit(1);
  }

  await warnIfDirtyWorktree();

  const tags = await listTags();
  const productionTags = tags.map(parseProductionTag).filter((v): v is SemverCore => v !== null);
  const preTags = tags.map(parsePreTag).filter((v): v is PreTag => v !== null);
  const alphaTags = preTags.filter((t) => t.channel === "alpha");
  const betaTags = preTags.filter((t) => t.channel === "beta");

  const latestProduction = maxCore(productionTags);
  const latestAlpha = maxPreTag(alphaTags);
  const latestBeta = maxPreTag(betaTags);

  if (mode === "production") {
    let core: SemverCore;
    if (explicit) {
      const parsed = parseCore(explicit);
      if (!parsed) {
        console.error(`Invalid version '${explicit}'. Expected X.Y.Z.`);
        Deno.exit(1);
      }
      core = parsed;
    } else if (latestBeta) {
      core = { major: latestBeta.major, minor: latestBeta.minor, patch: latestBeta.patch };
    } else if (latestAlpha) {
      core = { major: latestAlpha.major, minor: latestAlpha.minor, patch: latestAlpha.patch };
    } else if (latestProduction) {
      core = bumpPatch(latestProduction);
    } else {
      core = { major: 0, minor: 1, patch: 0 };
    }
    if (!explicit) {
      core = nextAvailablePatch(core, new Set(tags));
    }
    await createAndPushTag(`v${fmtCore(core)}`);
    return;
  }

  const channel = mode;
  let base: SemverCore;
  if (explicit) {
    const parsed = parseCore(explicit);
    if (!parsed) {
      console.error(`Invalid version '${explicit}'. Expected X.Y.Z.`);
      Deno.exit(1);
    }
    base = parsed;
  } else if (channel === "alpha" && latestAlpha) {
    base = { major: latestAlpha.major, minor: latestAlpha.minor, patch: latestAlpha.patch };
  } else if (channel === "beta" && latestBeta) {
    base = { major: latestBeta.major, minor: latestBeta.minor, patch: latestBeta.patch };
  } else if (channel === "beta" && latestAlpha) {
    base = { major: latestAlpha.major, minor: latestAlpha.minor, patch: latestAlpha.patch };
  } else if (latestProduction) {
    base = bumpPatch(latestProduction);
  } else {
    base = { major: 0, minor: 1, patch: 0 };
  }

  const existingForBase = preTags
    .filter((t) => t.channel === channel)
    .filter((t) => compareCore(t, base) === 0);
  const nextN = (existingForBase.length > 0 ? Math.max(...existingForBase.map((t) => t.number)) : 0) + 1;
  await createAndPushTag(`v${fmtCore(base)}-${channel}.${nextN}`);
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
    "agent/evals",
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
  console.log("portable backend build complete.");
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

async function commandEval(args: string[]): Promise<void> {
  const backendDir = join(repoRoot, "backend");
  const sub = args[0];
  if (sub === "list") {
    await run("uv", ["run", "python", "-m", "agent.evals", "--list"], { cwd: backendDir });
    return;
  }
  if (sub === "results") {
    const resultsDir = join(backendDir, "agent", "evals", "results");
    if (!(await pathExists(resultsDir))) {
      console.log("No results yet. Run 'stimma eval run' first.");
      return;
    }
    console.log("Recent eval runs:");
    const entries: string[] = [];
    for await (const entry of Deno.readDir(resultsDir)) {
      if (entry.isDirectory) entries.push(entry.name);
    }
    entries.sort().reverse();
    for (const name of entries.slice(0, 10)) {
      console.log(`  ${name}`);
    }
    console.log(`Results dir: ${resultsDir}`);
    return;
  }

  if (sub === "run") {
    const passThrough = args.slice(1);
    await run("uv", ["run", "python", "-m", "agent.evals", ...passThrough], { cwd: backendDir });
    return;
  }

  console.error("Usage: stimma eval {run|list|results}");
  Deno.exit(1);
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

async function testFrontend(args: string[]): Promise<void> {
  const backendPort = "19191";
  const frontendPort = "19192";

  const noServer = args.includes("--no-server");
  const verbose = args.includes("--verbose");
  const filteredArgs = args.filter((a) => a !== "--verbose" && a !== "--no-server");
  // Use "null" (discard) instead of "piped" to avoid pipe buffer deadlocks
  const stdio = verbose ? "inherit" as const : "null" as const;

  const env = {
    STIMMA_TEST_PROVIDER: "1",
    STIMMA_BACKEND_PORT: backendPort,
    STIMMA_FRONTEND_PORT: frontendPort,
  };

  let backend: Deno.ChildProcess | null = null;
  let frontend: Deno.ChildProcess | null = null;

  if (!noServer) {
    // Kill any stale processes from previous runs
    await killPort(backendPort);
    await killPort(frontendPort);

    console.log(`Starting e2e test backend on :${backendPort} (bundle=ai.stimma.stimma.e2e-test)...`);
    const backendCmd = new Deno.Command("uv", {
      args: ["run", "python", "main.py", "--bundle-id=ai.stimma.stimma.e2e-test", "--sandbox=default", `--port=${backendPort}`],
      cwd: join(repoRoot, "backend"),
      env: { ...Deno.env.toObject(), ...env },
      stdin: "null",
      stdout: stdio,
      stderr: stdio,
    });
    backend = backendCmd.spawn();

    console.log(`Starting e2e test frontend on :${frontendPort}...`);
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
    // Wait for both servers to be ready
    console.log("Waiting for backend...");
    await waitForHttp(`http://localhost:${backendPort}/api/profiles`);
    console.log("Waiting for frontend...");
    await waitForHttp(`http://localhost:${frontendPort}/`);
    console.log("Servers ready. Running Playwright tests...\n");

    // Build playwright args
    const pw = ["playwright", "test", "--config", "e2e/playwright.config.ts"];
    if (filteredArgs.includes("--ui")) {
      pw.push("--ui");
    } else {
      pw.push(...filteredArgs);
    }

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
      // Kill servers we started
      console.log("\nShutting down test servers...");
      try { frontend?.kill("SIGTERM"); } catch { /* already dead */ }
      try { backend?.kill("SIGTERM"); } catch { /* already dead */ }
      // Wait briefly for clean shutdown
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

const DEV_SKILLS_KEY = "dev_skills_dir";
const DEV_SKILLS_LINE_RE = /^dev_skills_dir:.*$/m;

async function commandSkills(args: string[], bundleId: string, sandbox: string): Promise<void> {
  const sub = args[0];
  if (sub !== "dev") {
    console.error(
      "Usage: stimma skills dev [path]   Set dev skills override (default: sibling stimma-skills)\n" +
      "       stimma skills dev --off    Clear the dev skills override",
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
    if (!DEV_SKILLS_LINE_RE.test(text)) {
      console.log("Dev skills override is not set; nothing to do.");
      return;
    }
    await Deno.writeTextFile(configPath, text.replace(/^dev_skills_dir:.*\n?/m, ""));
    console.log(`Cleared dev skills override in ${configPath} (backup: ${configPath}.bak).`);
    console.log("Backend reverts to profile-installed skills on next config reload.");
    return;
  }

  const raw = args[1] && !args[1].startsWith("--") ? args[1] : join(repoRoot, "..", "stimma-skills");
  const abs = resolve(raw);
  if (!(await pathExists(abs))) {
    console.error(`Skills directory not found: ${abs}`);
    Deno.exit(1);
  }

  const line = `${DEV_SKILLS_KEY}: ${JSON.stringify(abs)}`;
  const next = DEV_SKILLS_LINE_RE.test(text)
    ? text.replace(DEV_SKILLS_LINE_RE, line)
    : text.replace(/\s*$/, "") + "\n" + line + "\n";
  await Deno.writeTextFile(configPath, next);

  console.log(`Dev skills override set: ${abs}`);
  console.log(`Wrote ${configPath} (backup: ${configPath}.bak).`);
  console.log("These skills now shadow profile-installed built-ins; backend picks it up on config reload.");
}

// app_branch the backend's User-Agent reports for a bundle id when the
// distribution is official (mirrors backend/user_agent.py get_app_branch).
function appBranchForBundle(bundleId: string): string {
  if (bundleId === "ai.stimma.stimma") return "production";
  if (bundleId === "ai.stimma.stimma.beta") return "beta";
  if (bundleId === "ai.stimma.stimma.alpha") return "alpha";
  return "dev";
}

function officialBanner(bundleId: string): void {
  console.log(
    `⚠ STIMMA_DISTRIBUTION=official — telemetry/consent/thumbs/crash surfaces ACTIVE; ` +
      `events will be sent to the configured cloud (app_branch will be '${appBranchForBundle(bundleId)}')`,
  );
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
    if (args[0].startsWith("--channel=")) {
      channel = args[0].slice("--channel=".length);
      if (!(channel in CHANNEL_BUNDLE_IDS)) {
        console.error(`Unknown channel: ${channel}. Valid: ${Object.keys(CHANNEL_BUNDLE_IDS).join(", ")}`);
        Deno.exit(1);
      }
      args = args.slice(1);
      continue;
    }
    if (args[0].startsWith("--sandbox=")) {
      sandbox = args[0].slice("--sandbox=".length);
      args = args.slice(1);
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
        await run("npm", ["run", "dev"], { cwd: join(repoRoot, "frontend"), env: { ...portEnv, ...officialEnv } });
      } else if (sub === "backend") {
        const backendDir = join(repoRoot, "backend");
        const ports = await getSandboxPorts(bundleId, sandbox);
        const execStr = `uv run python main.py --bundle-id=${bundleId} --sandbox=${sandbox} --port=${ports.server}`;
        if (Deno.build.os === "windows") {
          const cmdArgs = ["nodemon", "--signal", "SIGKILL", "--exec", execStr];
          await run("npx", cmdArgs, { cwd: backendDir, env: officialEnv });
        } else {
          await run("npx", ["nodemon", "--signal", "SIGKILL", "--exec", execStr], { cwd: backendDir, env: officialEnv });
        }
      } else if (sub === "backend2") {
        const ports = await getSandboxPorts(bundleId, sandbox);
        const args2 = ["run", "--", "--bundle-id", bundleId, "--sandbox", sandbox, "--port", String(ports.server), "--console"];
        await run("cargo", args2, { cwd: join(repoRoot, "backend2"), env: officialEnv });
      } else if (sub === "app") {
        if (official) {
          console.log("Note: 'dev app' uses the externally running backend on :9191 — start it with 'stimma dev backend --official' for backend surfaces.");
        }
        await run("cargo", ["tauri", "dev"], { cwd: repoRoot, env: { STIMMA_DEV: "1", ...officialEnv } });
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
        await run("uv", args2, { cwd: join(repoRoot, "backend"), env: officialEnv });
      } else if (sub === "frontend") {
        const frontendDir = join(repoRoot, "frontend");
        await run("npm", ["run", "build"], { cwd: frontendDir, env: officialEnv });
        await run("npm", ["run", "preview"], { cwd: frontendDir, env: officialEnv });
      } else if (sub === "app") {
        if (official) {
          console.log("Note: 'run app' uses the externally running backend on :9191 — start it with 'stimma run backend --official' for backend surfaces.");
        }
        await run("cargo", ["run", "--release"], { cwd: repoRoot, env: { STIMMA_DEV: "1", ...officialEnv } });
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
      const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
      const backupDir = `${dataDir}-backup-${stamp}`;
      await copyDir(dataDir, backupDir);
      console.log(`Backup complete: ${backupDir}`);
      break;
    }

    case "test": {
      if (sub === "backend") {
        await run("uv", ["run", "pytest", ...rest], { cwd: join(repoRoot, "backend") });
      } else if (sub === "frontend") {
        await testFrontend(rest);
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
          const forkJsonPath = join(sandboxDir, ".fork.json");
          if (await pathExists(forkJsonPath)) {
            try {
              const data = JSON.parse(await Deno.readTextFile(forkJsonPath));
              ports = `  server=:${data.server_port} frontend=:${data.frontend_port}`;
            } catch { /* ignore */ }
          } else if (entry.name === "default") {
            ports = "  server=:9191 frontend=:9192";
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
          console.log(`Copying ${srcData} → ${dstData}...`);
          await copyDir(srcData, dstData);
        }
        await Deno.mkdir(dstCache, { recursive: true });
        // Allocate ports: scan existing .fork.json files to find next available pair
        const root = getBundleDataRoot(bundleId);
        const usedPorts = new Set<number>();
        for await (const entry of Deno.readDir(root)) {
          if (!entry.isDirectory || entry.name === "default") continue;
          const fp = join(root, entry.name, ".fork.json");
          try {
            const data = JSON.parse(await Deno.readTextFile(fp));
            usedPorts.add(data.server_port);
            usedPorts.add(data.frontend_port);
          } catch { /* ignore */ }
        }
        let serverPort = 9300;
        while (usedPorts.has(serverPort) || usedPorts.has(serverPort + 1)) {
          serverPort += 2;
        }
        if (serverPort > 9398) {
          console.error("No available fork ports (9300-9399 exhausted).");
          Deno.exit(1);
        }
        const forkConfig = { server_port: serverPort, frontend_port: serverPort + 1 };
        await Deno.writeTextFile(join(dstData, ".fork.json"), JSON.stringify(forkConfig, null, 2) + "\n");
        console.log(`Sandbox '${name}' created${empty ? " (empty, first-run)" : ""}.`);
        console.log(`  Server port:   ${serverPort}`);
        console.log(`  Frontend port: ${serverPort + 1}`);
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

    case "eval": {
      await commandEval(args.slice(1));
      break;
    }

    case "skills": {
      await commandSkills(args.slice(1), bundleId, sandbox);
      break;
    }

    case "tag": {
      await commandTag(args.slice(1));
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
