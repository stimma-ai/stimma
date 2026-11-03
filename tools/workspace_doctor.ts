/**
 * Read-only report of what a desktop's local storage would carry onto the shared
 * workspace, using the same rules as the app (frontend/src/utils/stateRegistry.ts).
 * Names and sizes only; values are never printed.
 */
import { join } from "https://deno.land/std@0.220.0/path/mod.ts";
import { instanceOfKey, isMigratedKey } from "../frontend/src/utils/stateRegistry.ts";

type Items = Record<string, string>;

interface Scope {
  tabs: { total: number; byType: Record<string, number>; pinned: number; preInstance: number };
  move: { count: number; bytes: number };
  closedTab: { count: number; bytes: number };
  stays: { count: number; bytes: number };
}

async function readStore(nativeBinary: string, leveldbDir: string): Promise<Items> {
  const cacheDir = await Deno.makeTempDir({ prefix: "stimma-doctor-" });
  const child = new Deno.Command(nativeBinary, {
    args: ["--cache-dir", cacheDir],
    stdin: "piped",
    stdout: "piped",
    stderr: "null",
  }).spawn();
  const writer = child.stdin.getWriter();
  const request = { id: 1, method: "read_chromium_local_storage", params: { db_path: leveldbDir } };
  await writer.write(new TextEncoder().encode(JSON.stringify(request) + "\n"));
  const reader = child.stdout.pipeThrough(new TextDecoderStream()).getReader();
  let buffered = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) throw new Error("the native helper exited without answering");
    buffered += value;
    for (const line of buffered.split("\n").slice(0, -1)) {
      const message = JSON.parse(line);
      if (message.id !== 1) continue;
      await writer.close().catch(() => {});
      child.kill();
      await Deno.remove(cacheDir, { recursive: true }).catch(() => {});
      if (message.error) throw new Error(JSON.stringify(message.error));
      return message.result.items;
    }
    buffered = buffered.slice(buffered.lastIndexOf("\n") + 1);
  }
}

function emptyScope(): Scope {
  return {
    tabs: { total: 0, byType: {}, pinned: 0, preInstance: 0 },
    move: { count: 0, bytes: 0 },
    closedTab: { count: 0, bytes: 0 },
    stays: { count: 0, bytes: 0 },
  };
}

/**
 * Splits stimma_<bundle>_<sandbox>_<token>_<rest>, where the token is a profile
 * id, a database guid or "global". None of the first three contain underscores.
 */
function splitKey(key: string) {
  const match = key.match(/^stimma_([^_]+)_([^_]+)_([^_]+)_(.+)$/);
  return match ? { server: `${match[1]} / ${match[2]}`, token: match[3], rest: match[4] } : null;
}

export function report(items: Items) {
  const servers = new Map<string, Map<string, Scope>>();
  const scopeFor = (server: string, token: string) => {
    if (!servers.has(server)) servers.set(server, new Map());
    const scopes = servers.get(server)!;
    if (!scopes.has(token)) scopes.set(token, emptyScope());
    return scopes.get(token)!;
  };

  const liveInstances = new Map<string, Set<string>>();
  for (const [key, value] of Object.entries(items)) {
    const parts = splitKey(key);
    if (!parts || parts.rest !== "workspace_tabs") continue;
    const scope = scopeFor(parts.server, parts.token);
    let tabs: any[] = [];
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) tabs = parsed;
    } catch { /* A broken list counts as empty, as it does in the app. */ }
    const live = liveInstances.get(parts.server) ?? new Set<string>();
    liveInstances.set(parts.server, live);
    for (const tab of tabs) {
      scope.tabs.total += 1;
      scope.tabs.byType[tab.type] = (scope.tabs.byType[tab.type] ?? 0) + 1;
      if (tab.pinned) scope.tabs.pinned += 1;
      if (tab.type === "tool" && !tab.instanceId) scope.tabs.preInstance += 1;
      if (tab.instanceId) live.add(String(tab.instanceId));
    }
  }

  for (const [key, value] of Object.entries(items)) {
    const parts = splitKey(key);
    if (!parts || parts.rest === "workspace_tabs") continue;
    const scope = scopeFor(parts.server, parts.token);
    const bucket = !isMigratedKey(parts.rest)
      ? scope.stays
      : (() => {
        const instance = instanceOfKey(parts.rest);
        return instance && !liveInstances.get(parts.server)?.has(instance) ? scope.closedTab : scope.move;
      })();
    bucket.count += 1;
    bucket.bytes += value.length;
  }
  return servers;
}

const kb = (bytes: number) => `${(bytes / 1024).toFixed(1)} KB`;

export async function workspaceDoctor(repoRoot: string, dataDir: string, args: string[]) {
  const fromIndex = args.indexOf("--from");
  const leveldbDir = fromIndex >= 0 ? args[fromIndex + 1] : join(dataDir, "chromium", "Local Storage", "leveldb");
  const candidates = ["release", "debug"].map(p => join(repoRoot, "native", "stimma-native", "target", p, "stimma-native"));
  const nativeBinary = candidates.find(path => {
    try { return Deno.statSync(path).isFile; } catch { return false; }
  });
  if (!nativeBinary) {
    console.error("Build the native helper first: cargo build --manifest-path native/stimma-native/Cargo.toml");
    Deno.exit(1);
  }
  const items = await readStore(nativeBinary, leveldbDir);
  console.log(`${Object.keys(items).length} keys in ${leveldbDir}\n`);
  for (const [server, scopes] of report(items)) {
    console.log(server);
    for (const [token, scope] of scopes) {
      const types = Object.entries(scope.tabs.byType).map(([type, n]) => `${n} ${type}`).join(", ");
      console.log(`  ${token}`);
      if (scope.tabs.total) {
        console.log(`    tabs: ${scope.tabs.total} (${types}), ${scope.tabs.pinned} pinned` +
          (scope.tabs.preInstance ? `, ${scope.tabs.preInstance} upgraded first` : ""));
      }
      console.log(`    moves: ${scope.move.count} (${kb(scope.move.bytes)})`);
      if (scope.closedTab.count) console.log(`    left with closed tabs: ${scope.closedTab.count} (${kb(scope.closedTab.bytes)})`);
      console.log(`    stays on device: ${scope.stays.count} (${kb(scope.stays.bytes)})`);
    }
  }
  console.log("\nA profile claims only if it has tabs. Masks and paint layers live in IndexedDB and aren't counted.");
}
