import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";
import { codeOf, HubError, objectPath, read, request, sessionChanged } from "./api";
import type { Connected, Connection, HubRequest, Identity, PendingCommand, Project, Reply, Snapshot, SyncEvent, SyncNotice } from "./types";

interface DisplayedReceipt { reply: Reply; key: string; generation: string; epoch: number }

function hasCommandReceipt(reply: Reply) {
  const task = reply.body.task;
  const id = reply.body.command_id ?? (task && typeof task === "object" && !Array.isArray(task)
    ? (task as Record<string, unknown>).command_id : undefined);
  return reply.status >= 200 && reply.status < 500 && typeof id === "string" && id.length > 0;
}

export function useHub() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connection, setConnection] = useState<Connection>("disconnected");
  const [error, setError] = useState("");
  const [events, setEvents] = useState<SyncEvent[]>([]);
  const [displayedReceipt, setDisplayedReceipt] = useState<DisplayedReceipt | null>(null);
  const [pending, setPending] = useState<PendingCommand[]>([]);
  const [busy, setBusy] = useState(false);
  const [renderedGeneration, setRenderedGeneration] = useState<string | null>(null);
  const project = useRef("");
  const revision = useRef(0);
  const epoch = useRef(0);
  const active = useRef<string | null>(null);
  const running = useRef(false);
  const transitions = useRef<Promise<void>>(Promise.resolve());
  const subscriptions = useRef<Promise<void>>(Promise.resolve());
  const current = useRef<Snapshot | null>(null);
  const subscription = useRef("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const receiver = useRef<(notice: SyncNotice) => void>(() => {});
  const matches = (generation: string, expected: number) =>
    active.current === generation && epoch.current === expected;

  const clearScope = () => {
    subscription.current = "";
    current.current = null;
    setSnapshot(null); setEvents([]); setDisplayedReceipt(null);
  };
  const denied = (reason: unknown) => {
    if (reason instanceof HubError && [401, 403].includes(reason.status)) {
      ++epoch.current; ++revision.current; active.current = null; running.current = false; setRenderedGeneration(null);
      clearTimeout(timer.current); clearScope(); setBusy(false); setProjects([]); setPending([]); setConnection("revoked");
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
  const subscribe = (value: Snapshot, generation: string, expected: number, sequence: number) => {
    const next = subscriptions.current.then(async () => {
      if (!matches(generation, expected) || sequence !== revision.current) throw new HubError("session_changed");
      const id = crypto.randomUUID();
      subscription.current = id;
      await invoke("hub_subscribe", { projectId: value.project.project_id, streamId: value.stream_id,
        after: value.cursor, permissionRevision: value.project.permission_revision, subscriptionId: id, generation });
      if (!matches(generation, expected) || sequence !== revision.current) throw new HubError("session_changed");
    });
    subscriptions.current = next.catch(() => {});
    return next;
  };

  const refresh = async (id = project.current, reset = false, generation = renderedGeneration) => {
    const expected = epoch.current;
    if (!id || !generation || !matches(generation, expected)) return;
    const sequence = ++revision.current;
    clearTimeout(timer.current);
    subscription.current = "";
    if (reset) clearScope();
    setConnection("syncing");
    try {
      const next = await read<Snapshot>(generation, objectPath(id, "snapshot", "").replace(/\/$/, ""));
      if (!matches(generation, expected) || sequence !== revision.current || id !== project.current) return;
      if (next.schema_revision !== "p1-sync-r1" || next.project.project_id !== id) {
        clearScope(); setConnection("incompatible"); return;
      }
      current.current = next; setSnapshot(next); setError("");
      await subscribe(next, generation, expected, sequence);
    } catch (reason) {
      if (!matches(generation, expected) || sequence !== revision.current) return;
      setError(codeOf(reason));
      if (denied(reason)) return;
      setConnection("offline");
      timer.current = setTimeout(() => { if (matches(generation, expected)) void refresh(id, true, generation); }, 4000);
    }
  };

  receiver.current = notice => {
    if (notice.subscription_id !== subscription.current) return;
    const value = current.current;
    const generation = active.current;
    const expected = epoch.current;
    if (!value || !generation) return;
    if (notice.kind === "batch") {
      const batch = notice.data;
      if (!batch || batch.schema_revision !== "p1-sync-r1" || batch.stream_id !== value.stream_id
          || !Number.isSafeInteger(batch.cursor) || batch.cursor < value.cursor
          || batch.events.length > 32 || batch.events.some((e, i) =>
            e.project_id !== value.project.project_id || e.cursor !== value.cursor + i + 1)
          || batch.cursor !== (batch.events.at(-1)?.cursor ?? value.cursor)) {
        void refresh(project.current, true, generation); return;
      }
      setConnection("live");
      if (batch.events.length) {
        setEvents(previous => [...batch.events, ...previous].slice(0, 100));
        void refresh(project.current, false, generation);
      }
    } else if (notice.kind === "access_revoked") {
      denied(new HubError("access_revoked", 403));
    } else if (notice.kind === "incompatible") {
      clearScope(); setConnection("incompatible");
    } else if (notice.kind === "reset") {
      void refresh(project.current, true, generation);
    } else if (notice.kind === "end") {
      const sequence = revision.current;
      void subscribe(value, generation, expected, sequence).catch(reason => {
        if (matches(generation, expected) && sequence === revision.current) {
          setError(codeOf(reason)); setConnection("offline");
        }
      });
    } else {
      setConnection("offline");
      timer.current = setTimeout(() => {
        if (matches(generation, expected)) void refresh(project.current, true, generation);
      }, 4000);
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
    if (!shown || !hasCommandReceipt(shown.reply) || !matches(shown.generation, shown.epoch)) return;
    void invoke("hub_ack", { generation: shown.generation, key: shown.key }).then(() => {
      if (matches(shown.generation, shown.epoch)) {
        setPending(previous => previous.filter(item => item.idempotency_key !== shown.key));
      }
    }).catch(reason => {
      if (matches(shown.generation, shown.epoch)) setError(codeOf(reason) + " · 回执保留在本机");
    });
  }, [displayedReceipt]);

  const selectProject = (id: string, generation = renderedGeneration) => {
    if (!generation || generation !== active.current) return;
    project.current = id; setEvents([]); setDisplayedReceipt(null); void refresh(id, true, generation);
  };
  const connect = async (baseUrl: string, importCredential: boolean, devLoopback: boolean) => {
    const expected = ++epoch.current;
    ++revision.current; active.current = null; running.current = false; setRenderedGeneration(null);
    clearTimeout(timer.current); project.current = ""; clearScope();
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
    ++revision.current; active.current = null; running.current = false; setRenderedGeneration(null); project.current = "";
    clearTimeout(timer.current); clearScope();
    setBusy(false); setIdentity(null); setProjects([]); setPending([]); setConnection("disconnected");
    try { await transition(forget); }
    catch (reason) { if (epoch.current === expected) setError(codeOf(reason)); }
  };
  const query = async <T,>(route: string): Promise<T> => {
    const generation = renderedGeneration;
    const expected = epoch.current;
    if (!generation || !matches(generation, expected)) throw new HubError("session_changed");
    try {
      const value = await read<T>(generation, route);
      if (!matches(generation, expected)) throw new HubError("session_changed");
      return value;
    } catch (reason) {
      if (!matches(generation, expected)) throw new HubError("session_changed");
      if (!sessionChanged(reason)) { denied(reason); setError(codeOf(reason)); }
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
      setDisplayedReceipt({ reply: result, key, generation, epoch: expected });
      if ((result.status === 401 || result.status === 403) && !hasCommandReceipt(result)) {
        denied(new HubError(String(result.body.code), result.status)); return;
      }
      if (result.status >= 400) setError(String(result.body.code ?? "command_rejected")
        + (hasCommandReceipt(result) ? "" : " · 原命令可能仍待核对"));
      void refresh(project.current, false, generation);
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
  return { identity, projects, snapshot, connection, error, events, receipt: displayedReceipt?.reply ?? null, pending, busy,
    connect, disconnect, selectProject, refresh, query, command,
    retry: (original: PendingCommand) => {
      if (!busy && connection === "live") void execute(original, true, original.generation);
    },
    writable: connection === "live" && !busy,
    can: (action: string) => connection === "live" && !busy && !!snapshot?.available_actions.includes(action),
  };
}

export type Hub = ReturnType<typeof useHub>;
