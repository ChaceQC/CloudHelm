import { invoke } from "@tauri-apps/api/core";
import type { HubRequest, Json, Reply } from "./types";

export class HubError extends Error {
  constructor(public code: string, public status = 0) { super(code); }
}

export async function request(input: HubRequest): Promise<Reply> {
  try { return await invoke<Reply>("hub_request", { request: input }); }
  catch (error) { throw new HubError(typeof error === "string" ? error : "hub_unavailable"); }
}

export async function read<T>(route: string): Promise<T> {
  const reply = await request({ method: "GET", route });
  if (reply.status !== 200) throw new HubError(String(reply.body.code ?? "query_failed"), reply.status);
  return reply.body as T;
}

export const objectPath = (project: string, kind: string, id: string) =>
  `/api/projects/${encodeURIComponent(project)}/${kind}/${encodeURIComponent(id)}`;
export const taskPath = (id: string) => `/api/tasks/${encodeURIComponent(id)}`;
export const stringify = (value: unknown) => JSON.stringify(value, null, 2);
export const codeOf = (error: unknown) => error instanceof Error ? error.message : String(error);
export const bodyOf = (value: unknown): Json => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("json_object_required");
  return value as Json;
};
