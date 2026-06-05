const DEBUG_QUERY_PARAM = 'editorDebug';
const DEBUG_STORAGE_KEY = 'stimma:editor-debug';
const DEBUG_GLOBAL_KEY = '__STIMMA_EDITOR_DEBUG__';
const DEBUG_BUFFER_LIMIT = 400;

type DebugEvent = {
  seq: number;
  timestamp: string;
  source: string;
  event: string;
  details?: Record<string, unknown>;
};

type DebugStore = {
  enabled?: boolean;
  seq: number;
  sessionCounters: Record<string, number>;
  events: DebugEvent[];
};

function getGlobalStore(): DebugStore {
  const target = globalThis as typeof globalThis & {
    [DEBUG_GLOBAL_KEY]?: DebugStore;
  };

  if (!target[DEBUG_GLOBAL_KEY]) {
    target[DEBUG_GLOBAL_KEY] = {
      seq: 0,
      sessionCounters: {},
      events: [],
    };
  }

  return target[DEBUG_GLOBAL_KEY]!;
}

export function isEditorDebugEnabled(): boolean {
  const store = getGlobalStore();

  if (typeof store.enabled === 'boolean') {
    return store.enabled;
  }

  if (typeof window === 'undefined') {
    store.enabled = false;
    return false;
  }

  const params = new URLSearchParams(window.location.search);
  const queryValue = params.get(DEBUG_QUERY_PARAM);
  if (queryValue === '1') {
    store.enabled = true;
    try {
      window.localStorage.setItem(DEBUG_STORAGE_KEY, '1');
    } catch {
      // Ignore storage failures.
    }
    return true;
  }

  try {
    store.enabled = window.localStorage.getItem(DEBUG_STORAGE_KEY) === '1';
  } catch {
    store.enabled = false;
  }

  return store.enabled;
}

export function nextEditorDebugSession(kind: string): number {
  const store = getGlobalStore();
  store.sessionCounters[kind] = (store.sessionCounters[kind] ?? 0) + 1;
  return store.sessionCounters[kind];
}

export function logEditorDebug(
  source: string,
  event: string,
  details?: Record<string, unknown>
): void {
  if (!isEditorDebugEnabled()) {
    return;
  }

  const store = getGlobalStore();
  const entry: DebugEvent = {
    seq: ++store.seq,
    timestamp: new Date().toISOString(),
    source,
    event,
    details,
  };

  store.events.push(entry);
  if (store.events.length > DEBUG_BUFFER_LIMIT) {
    store.events.splice(0, store.events.length - DEBUG_BUFFER_LIMIT);
  }

  console.log(`[EditorDebug] ${source}:${event}`, details ?? {});
}

export function getRecentEditorDebugEvents(limit: number = 40): DebugEvent[] {
  const store = getGlobalStore();
  return store.events.slice(-limit);
}

export function summarizeEditorDebugError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
    };
  }

  return {
    value: String(error),
  };
}

export function clearEditorDebugEvents(): void {
  const store = getGlobalStore();
  store.events = [];
}
