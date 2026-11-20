import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";
import { codeOf, HubError, objectPath, read, request, sessionChanged, taskPath } from "./api";
import type { CommandReceipt, Connected, Connection, HubRequest, Identity, PendingCommand, Project, Reply, Snapshot, SyncEvent, SyncNotice, Task } from "./types";

interface DisplayedReceipt { receipt: CommandReceipt; generation: string; epoch: number }
interface TaskChange { cursor: number; version: number }
interface SyncScope {
  projectId: string; streamId: string; permissionRevision: number;
  consumedCursor: number; subscriptionId: string; live: boolean;
  taskChanges: Map<string, TaskChange>; runVersions: Map<string, number>;
}
const EVENT_LIMIT = 100;

export function useHub() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [taskViews, setTaskViews] = useState(() => new Map<string, { cursor: number; task: Task }>());
  const [connection, setConnection] = useState<Connection>("disconnected");
  const [error, setError] = useState("");
  const [events, setEvents] = useState<SyncEvent[]>([]);
  const [displayedReceipt, setDisplayedReceipt] = useState<DisplayedReceipt | null>(null);
  const [pending, setPending] = useState<PendingCommand[]>([]);
  const [busy, setBusy] = useState(false);
  const [renderedGeneration, setRenderedGeneration] = useState<string | null>(null);
  const [previewRevision, setPreviewRevision] = useState(0);
  const project = useRef("");
  const revision = useRef(0);
  const epoch = useRef(0);
  const active = useRef<string | null>(null);
  const running = useRef(false);
  const transitions = useRef<Promise<void>>(Promise.resolve());
  const subscriptions = useRef<Promise<void>>(Promise.resolve());
  const snapshotFlights = useRef(new Map<string, { trailingRevision?: number }>());
  const scope = useRef<SyncScope | null>(null);
  const snapshotReady = useRef(false);
  const previewEpoch = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const receiver = useRef<(notice: SyncNotice) => void>(() => {});
  const matches = (generation: string, expected: number) =>
    active.current === generation && epoch.current === expected;
  const closePreviews = () => {
    ++previewEpoch.current;
    void invoke("preview_close_all").catch(() => {});
    setPreviewRevision(previewEpoch.current);
  };

  const clearScope = () => {
    ++revision.current;
    clearTimeout(timer.current);
    scope.current = null;
    snapshotReady.current = false;
    closePreviews();
    setSnapshot(null); setTaskViews(new Map()); setEvents([]); setDisplayedReceipt(null);
  };
  const denied = (reason: unknown) => {
    if (reason instanceof HubError && [401, 403].includes(reason.status)) {
      ++epoch.current; active.current = null; running.current = false; setRenderedGeneration(null);
      clearScope(); setBusy(false); setProjects([]); setPending([]); setConnection("revoked");
      return true;
    }
    return false;
  };
  const transition = (forget: boolean) => {
    const next = transitions.current.then(() => invoke<string>("hub_transition", { forget }));
    transitions.current = next.then(() => {}, () => {});
    return next;
  };
  const loadPending = async (generation: string, expected: number) => {
    const original = await invoke<HubRequest[]>("hub_pending", { generation });
    if (!matches(generation, expected)) throw new HubError("session_changed");
    const commands = original.map(item => ({ ...item, generation }));
    setPending(commands);
    return commands;
  };
  const retrySync = (generation: string) => {
    setConnection("offline");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { void refresh(project.current, generation); }, 4000);
  };
  const subscribe = (value: SyncScope, generation: string) => {
    subscriptions.current = subscriptions.current.then(async () => {
      if (scope.current !== value || value.subscriptionId) return;
      const id = crypto.randomUUID();
      value.subscriptionId = id;
      await invoke("hub_subscribe", { projectId: value.projectId, streamId: value.streamId,
        after: value.consumedCursor, permissionRevision: value.permissionRevision, subscriptionId: id, generation }).catch(reason => {
        if (scope.current !== value || value.subscriptionId !== id) return;
        value.subscriptionId = ""; value.live = false;
        setError(codeOf(reason)); retrySync(generation);
      });
    });
  };

  const refresh = async (id = project.current, generation = renderedGeneration) => {
    const expected = epoch.current;
    if (!id || id !== project.current || !generation || !matches(generation, expected)) return;
    // The snapshot route learns the stream and permission revision from its reply.
    const key = JSON.stringify([generation, id]);
    const inFlight = snapshotFlights.current.get(key);
    if (inFlight) { inFlight.trailingRevision = revision.current; return; }
    const flight: { trailingRevision?: number } = {};
    snapshotFlights.current.set(key, flight);
    const sequence = revision.current;
    const selected = () => matches(generation, expected) && id === project.current;
    const applies = () => selected() && sequence === revision.current;
    clearTimeout(timer.current);
    snapshotReady.current = false;
    setConnection("syncing");
    try {
      const next = await read<Snapshot>(generation, objectPath(id, "snapshot", "").replace(/\/$/, ""));
      if (!applies()) return;
      if (next.schema_revision !== "p1-sync-r1" || next.project.project_id !== id) {
        clearScope(); setConnection("incompatible"); return;
      }
      const previous = scope.current;
      if (previous && (next.stream_id !== previous.streamId || next.project.permission_revision !== previous.permissionRevision)) {
        clearScope();
      }
      // Only a new scope takes its starting cursor from a snapshot.
      const value = (scope.current ??= { projectId: id, streamId: next.stream_id,
        permissionRevision: next.project.permission_revision, consumedCursor: next.cursor, subscriptionId: "", live: false,
        taskChanges: new Map(), runVersions: new Map() });
      value.taskChanges = new Map(next.tasks.map(task => {
        const newer = value.taskChanges.get(task.task_id);
        return [task.task_id, newer && newer.cursor > next.cursor ? newer : { cursor: next.cursor, version: task.version }];
      }));
      clearTimeout(timer.current);
      snapshotReady.current = true;
      setTaskViews(previous => new Map([...previous].filter(([, item]) => item.cursor > next.cursor)));
      setSnapshot(next); setError("");
      if (value.live) setConnection("live");
      if (!value.subscriptionId) subscribe(value, generation);
    } catch (reason) {
      if (!applies()) return;
      const code = codeOf(reason);
      setError(code);
      if (denied(reason)) return;
      if (code === "api_schema_not_supported") { clearScope(); setConnection("incompatible"); return; }
      retrySync(generation);
    } finally {
      snapshotFlights.current.delete(key);
      if (flight.trailingRevision === revision.current && selected()) void refresh(id, generation);
    }
  };

  const refreshTask = async (value: SyncScope, generation: string, id: string, change: TaskChange) => {
    const current = () => scope.current === value && value.taskChanges.get(id) === change;
    try {
      const task = await read<Task>(generation, taskPath(id));
      if (!current()) return;
      if (task.task_id !== id || task.project_id !== value.projectId || task.version < change.version) {
        void refresh(value.projectId, generation); return;
      }
      change.version = task.version;
      setTaskViews(previous => new Map(previous).set(id, { cursor: change.cursor, task }));
    } catch (reason) {
      if (current() && !denied(reason)) void refresh(value.projectId, generation);
    }
  };

  receiver.current = notice => {
    const value = scope.current;
    const generation = active.current;
    if (!value || notice.subscription_id !== value.subscriptionId || !generation) return;
    if (notice.kind === "batch") {
      const batch = notice.data;
      if (!batch || batch.schema_revision !== "p1-sync-r1" || batch.stream_id !== value.streamId
          || !Number.isSafeInteger(batch.cursor) || batch.cursor < value.consumedCursor
          || !Array.isArray(batch.events) || batch.events.length > 32 || batch.events.some((e, i) =>
            e.project_id !== value.projectId || e.cursor !== value.consumedCursor + i + 1
            || !Number.isSafeInteger(e.aggregate_version) || e.aggregate_version < 0)
          || batch.cursor !== (batch.events.at(-1)?.cursor ?? value.consumedCursor)) {
        clearScope(); void refresh(value.projectId, generation); return;
      }
      value.consumedCursor = batch.cursor;
      value.live = true;
      if (batch.events.some(event => event.event_type === "preview.revocation_requested"
          || event.event_type === "preview.stop_requested")) closePreviews();
      const changedTasks = new Map<string, TaskChange>();
      let needsSnapshot = false;
      const recent = batch.events.filter(event => {
        const id = event.aggregate_id;
        if (event.aggregate_kind === "agent_run") {
          if ((value.runVersions.get(id) ?? -1) >= event.aggregate_version) return false;
          value.runVersions.delete(id);
          value.runVersions.set(id, event.aggregate_version);
          if (value.runVersions.size > EVENT_LIMIT) value.runVersions.delete(value.runVersions.keys().next().value!);
          return true;
        }
        const queued = event.event_type === "task.agent_run_queued" && event.schema_version === "p2-task-agent-event-r1";
        const task = value.taskChanges.get(id);
        if (event.aggregate_kind === "task" && task && (queued || event.schema_version === "p1-task-event-r1"
            || event.schema_version === "p2-work-item-accepted-event-r1"
            || (event.schema_version === "p2-verification-r1" && event.event_type === "verification.accepted"))) {
          // A new Run changes the Task projection even when the Task revision is unchanged.
          if (queued || event.aggregate_version > task.version) {
            const change = { cursor: event.cursor, version: Math.max(task.version, event.aggregate_version) };
            value.taskChanges.set(id, change);
            changedTasks.set(id, change);
          }
        } else needsSnapshot = true;
        return true;
      }).reverse();
      if (recent.length) setEvents(previous => [...recent, ...previous].slice(0, EVENT_LIMIT));
      if (needsSnapshot) void refresh(value.projectId, generation);
      else {
        for (const [id, change] of changedTasks) void refreshTask(value, generation, id, change);
        if (snapshotReady.current) setConnection("live");
      }
    } else if (notice.kind === "access_revoked") {
      denied(new HubError("access_revoked", 403));
    } else if (notice.kind === "incompatible") {
      clearScope(); setConnection("incompatible");
    } else if (notice.kind === "reset") {
      clearScope(); void refresh(value.projectId, generation);
    } else {
      value.subscriptionId = "";
      if (notice.kind === "end") subscribe(value, generation);
      else { value.live = false; retrySync(generation); }
    }
  };

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void listen<SyncNotice>("hub-sync", e => receiver.current(e.payload)).then(stop => {
      if (cancelled) stop(); else unlisten = stop;
    }).catch(() => setError("请使用 Windows Desktop 原生程序连接 Hub"));
    return () => { cancelled = true; unlisten?.(); clearTimeout(timer.current); };
  }, []);

  // Keep confirmed replies durable until the current session has actually rendered them.
  useEffect(() => {
    const shown = displayedReceipt;
    if (!shown || !matches(shown.generation, shown.epoch)) return;
    const key = shown.receipt.idempotency_key;
    void invoke("hub_ack", { generation: shown.generation, key }).then(() => {
      if (matches(shown.generation, shown.epoch)) {
        setPending(previous => previous.filter(item => item.idempotency_key !== key));
      }
    }).catch(reason => {
      if (matches(shown.generation, shown.epoch)) setError(codeOf(reason) + " · 回执保留在本机");
    });
  }, [displayedReceipt]);

  const selectProject = (id: string, generation = renderedGeneration) => {
    if (!id || !generation || generation !== active.current) return;
    if (id !== project.current) {
      if (project.current) clearScope();
      project.current = id;
    }
    void refresh(id, generation);
  };
  const connect = async (baseUrl: string, importCredential: boolean, devLoopback: boolean) => {
    const expected = ++epoch.current;
    active.current = null; running.current = false; setRenderedGeneration(null);
    project.current = ""; clearScope();
    setBusy(false); setIdentity(null); setProjects([]); setPending([]); setError(""); setConnection("connecting");
    try {
      const generation = await transition(false);
      if (epoch.current !== expected) return;
      const connected = await invoke<Connected>("hub_connect", { generation, baseUrl, importCredential, devLoopback });
      if (epoch.current !== expected || connected.generation !== generation) return;
      active.current = generation;
      setRenderedGeneration(generation);
      setIdentity(connected.identity);
      await loadPending(generation, expected);
      const page = await read<{ items: Project[]; next_cursor: string | null }>(generation, "/api/projects");
      if (!matches(generation, expected)) return;
      setProjects(page.items);
      if (page.next_cursor) setError("项目列表仅显示首批；可按项目 ID 打开其他项目");
      if (page.items[0]) selectProject(page.items[0].project_id, generation);
      else setConnection("live");
    } catch (reason) {
      if (epoch.current !== expected) return;
      setError(codeOf(reason)); if (!denied(reason)) setConnection("disconnected");
    }
  };
  const disconnect = async (forget = false) => {
    const expected = ++epoch.current;
    active.current = null; running.current = false; setRenderedGeneration(null); project.current = "";
    clearScope();
    setBusy(false); setIdentity(null); setProjects([]); setPending([]); setConnection("disconnected");
    try { await transition(forget); }
    catch (reason) { if (epoch.current === expected) setError(codeOf(reason)); }
  };
  const openPreview = async (environmentId: string, expected: number) => {
    const generation = renderedGeneration;
    if (!generation || generation !== active.current || !scope.current || previewEpoch.current !== expected) {
      throw new HubError("session_changed");
    }
    const label = await invoke<string>("preview_open", { generation, environmentId }).catch(reason => {
      throw previewEpoch.current === expected ? reason : new HubError("session_changed");
    });
    if (previewEpoch.current !== expected) {
      await invoke("preview_close", { label }).catch(() => {});
      throw new HubError("session_changed");
    }
  };
  const query = async <T,>(route: string, isCurrent?: () => boolean): Promise<T> => {
    const generation = renderedGeneration;
    const expected = epoch.current;
    if (!generation) throw new HubError("session_changed");
    const requestScope = scope.current;
    const matchesQuery = () => matches(generation, expected)
      && scope.current === requestScope && (!isCurrent || isCurrent());
    if (!matchesQuery()) throw new HubError("session_changed");
    try {
      const value = await read<T>(generation, route);
      if (!matchesQuery()) throw new HubError("session_changed");
      return value;
    } catch (reason) {
      if (!matchesQuery()) throw new HubError("session_changed");
      // Scoped callers display their own errors; current authorization failures still revoke access here.
      if (!sessionChanged(reason) && (denied(reason) || !isCurrent)) setError(codeOf(reason));
      throw reason;
    }
  };
  const execute = async (command: HubRequest, retry = false, owner = renderedGeneration) => {
    const generation = owner;
    const expected = epoch.current;
    const key = command.idempotency_key;
    if (!generation || !matches(generation, expected) || !key || running.current) return;
    running.current = true; setBusy(true); setDisplayedReceipt(null); setError("");
    setPending(previous => previous.some(item => item.idempotency_key === key)
      ? previous : [...previous, { ...command, generation }]);
    try {
      const result = retry ? await invoke<Reply>("hub_retry", { generation, key }) : await request(generation, command);
      if (!matches(generation, expected)) return;
      try { await loadPending(generation, expected); }
      catch (reason) {
        if (!matches(generation, expected)) return;
        setError(codeOf(reason) + " · 无法读取原命令日志");
      }
      if (!matches(generation, expected)) return;
      if (!result.receipt) {
        const code = String(result.body.code ?? "command_unconfirmed");
        if (!denied(new HubError(code, result.status))) setError(`${code} · 原命令结果待核对`);
        return;
      }
      setDisplayedReceipt({ receipt: result.receipt, generation, epoch: expected });
      void refresh(project.current, generation);
    } catch (reason) {
      if (!matches(generation, expected)) return;
      let unresolved: boolean | undefined;
      try {
        const commands = await loadPending(generation, expected);
        unresolved = commands.some(item => item.idempotency_key === key);
      } catch {
        if (!matches(generation, expected)) return;
      }
      if (!matches(generation, expected)) return;
      setError(codeOf(reason) + (unresolved === undefined ? " · 无法读取原命令日志"
        : unresolved ? " · 原命令结果待核对" : ""));
    } finally {
      if (matches(generation, expected)) { running.current = false; setBusy(false); }
    }
  };
  const command = (route: string, body: Record<string, unknown>) => {
    if (!renderedGeneration || renderedGeneration !== active.current || connection !== "live" || busy || running.current) return;
    if (pending.some(p => p.route === route)) { setError("请先核对同一操作入口的原命令"); return; }
    void execute({ method: "POST", route, body, idempotency_key: crypto.randomUUID() });
  };
  const tasks = snapshot?.tasks.map(task => {
    const latest = taskViews.get(task.task_id)?.task;
    return latest && latest.version >= task.version ? latest : task;
  }) ?? [];
  return { identity, projects, snapshot, tasks, connection, error, events, previewRevision,
    receipt: displayedReceipt?.receipt ?? null, pending, busy,
    connect, disconnect, selectProject, refresh, query, command, openPreview, closePreviews, generation: renderedGeneration,
    retry: (original: PendingCommand) => {
      if (!busy && connection === "live") void execute(original, true, original.generation);
    },
    writable: connection === "live" && !busy,
    can: (action: string) => connection === "live" && !busy && !!snapshot?.available_actions.includes(action),
  };
}

export type Hub = ReturnType<typeof useHub>;
