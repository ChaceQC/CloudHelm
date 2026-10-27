import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";
import { codeOf, HubError, objectPath, read, request } from "./api";
import type { Connection, HubRequest, Identity, Project, Reply, Snapshot, SyncEvent, SyncNotice } from "./types";

export function useHub() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connection, setConnection] = useState<Connection>("disconnected");
  const [error, setError] = useState("");
  const [events, setEvents] = useState<SyncEvent[]>([]);
  const [receipt, setReceipt] = useState<Reply | null>(null);
  const [pending, setPending] = useState<HubRequest[]>([]);
  const [busy, setBusy] = useState(false);
  const project = useRef("");
  const revision = useRef(0);
  const current = useRef<Snapshot | null>(null);
  const subscription = useRef("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const receiver = useRef<(notice: SyncNotice) => void>(() => {});

  const clearScope = () => {
    subscription.current = "";
    current.current = null;
    setSnapshot(null); setEvents([]); setReceipt(null);
  };
  const denied = (reason: unknown) => {
    if (reason instanceof HubError && [401, 403].includes(reason.status)) {
      clearScope(); setProjects([]); setPending([]); setConnection("revoked");
      return true;
    }
    return false;
  };
  const subscribe = async (value: Snapshot) => {
    const id = crypto.randomUUID();
    subscription.current = id;
    await invoke("hub_subscribe", { projectId: value.project.project_id, streamId: value.stream_id,
      after: value.cursor, permissionRevision: value.project.permission_revision, subscriptionId: id });
  };

  const refresh = async (id = project.current, reset = false) => {
    if (!id) return;
    const generation = ++revision.current;
    clearTimeout(timer.current);
    subscription.current = "";
    if (reset) clearScope();
    setConnection("syncing");
    try {
      const next = await read<Snapshot>(objectPath(id, "snapshot", "").replace(/\/$/, ""));
      if (generation !== revision.current || id !== project.current) return;
      if (next.schema_revision !== "p1-sync-r1" || next.project.project_id !== id) {
        clearScope(); setConnection("incompatible"); return;
      }
      current.current = next; setSnapshot(next); setError("");
      await subscribe(next);
    } catch (reason) {
      if (generation !== revision.current) return;
      setError(codeOf(reason));
      if (denied(reason)) return;
      setConnection("offline");
      timer.current = setTimeout(() => { void refresh(id, true); }, 4000);
    }
  };

  receiver.current = notice => {
    if (notice.subscription_id !== subscription.current) return;
    const value = current.current;
    if (!value) return;
    if (notice.kind === "batch") {
      const batch = notice.data;
      if (!batch || batch.schema_revision !== "p1-sync-r1" || batch.stream_id !== value.stream_id
          || !Number.isSafeInteger(batch.cursor) || batch.cursor < value.cursor
          || batch.events.length > 32 || batch.events.some((e, i) =>
            e.project_id !== value.project.project_id || e.cursor !== value.cursor + i + 1)
          || batch.cursor !== (batch.events.at(-1)?.cursor ?? value.cursor)) {
        void refresh(project.current, true); return;
      }
      setConnection("live");
      if (batch.events.length) {
        setEvents(previous => [...batch.events, ...previous].slice(0, 100));
        void refresh();
      }
    } else if (notice.kind === "access_revoked") {
      clearScope(); setProjects([]); setPending([]); setConnection("revoked");
    } else if (notice.kind === "incompatible") {
      clearScope(); setConnection("incompatible");
    } else if (notice.kind === "reset") {
      void refresh(project.current, true);
    } else if (notice.kind === "end") {
      // A finite stream closes normally; reauthorize from the last consistent snapshot.
      void subscribe(value).catch(reason => { setError(codeOf(reason)); setConnection("offline"); });
    } else {
      setConnection("offline");
      timer.current = setTimeout(() => { void refresh(project.current, true); }, 4000);
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

  const selectProject = (id: string) => {
    project.current = id; setEvents([]); setReceipt(null); void refresh(id, true);
  };
  const connect = async (baseUrl: string, importCredential: boolean, devLoopback: boolean) => {
    ++revision.current; clearTimeout(timer.current); project.current = ""; clearScope();
    setIdentity(null); setProjects([]); setPending([]); setError(""); setConnection("connecting");
    try {
      const who = await invoke<Identity>("hub_connect", { baseUrl, importCredential, devLoopback });
      setIdentity(who);
      const original = await invoke<HubRequest[]>("hub_pending");
      setPending(original);
      const page = await read<{ items: Project[]; next_cursor: string | null }>("/api/projects");
      setProjects(page.items);
      if (page.next_cursor) setError("项目列表仅显示首批；可按项目 ID 打开其他项目");
      if (page.items[0]) selectProject(page.items[0].project_id);
      else setConnection("live");
    } catch (reason) { setError(codeOf(reason)); if (!denied(reason)) setConnection("disconnected"); }
  };
  const disconnect = async (forget = false) => {
    ++revision.current; project.current = ""; clearTimeout(timer.current); clearScope();
    setIdentity(null); setProjects([]); setPending([]); setConnection("disconnected");
    try { await invoke("hub_disconnect", { forget }); }
    catch (reason) { setError(codeOf(reason)); }
  };
  const query = async <T,>(route: string): Promise<T> => {
    try { return await read<T>(route); }
    catch (reason) { denied(reason); setError(codeOf(reason)); throw reason; }
  };
  const execute = async (command: HubRequest) => {
    setBusy(true); setPending(previous => previous.some(p => p.idempotency_key === command.idempotency_key)
      ? previous : [...previous, command]); setReceipt(null); setError("");
    try {
      const result = await request(command);
      setReceipt(result);
      const original = await invoke<HubRequest[]>("hub_pending");
      setPending(original);
      if (result.status === 401 || result.status === 403) {
        denied(new HubError(String(result.body.code), result.status)); return;
      }
      if (result.status >= 400) setError(String(result.body.code ?? "command_rejected"));
      await refresh();
    } catch (reason) { setError(`${codeOf(reason)} · 原命令结果待核对`); }
    finally { setBusy(false); }
  };
  const command = (route: string, body: Record<string, unknown>) => {
    if (connection !== "live" || busy) return;
    if (pending.some(p => p.route === route)) { setError("请先核对同一操作入口的原命令"); return; }
    void execute({ method: "POST", route, body, idempotency_key: crypto.randomUUID() });
  };
  return { identity, projects, snapshot, connection, error, events, receipt, pending, busy,
    connect, disconnect, selectProject, refresh, query, command,
    retry: (original: HubRequest) => { if (!busy && connection === "live") void execute(original); },
    writable: connection === "live" && !busy,
    can: (action: string) => connection === "live" && !busy && !!snapshot?.available_actions.includes(action),
  };
}

export type Hub = ReturnType<typeof useHub>;
