export type Note = {
  id: number;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
};

export type NoteInput = Pick<Note, "title" | "body">;

async function request<T>(path: string, expectedStatus: number, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("无法连接到服务，请检查服务状态后重试。");
  }

  if (response.status === 404) {
    throw new Error("这条便签不存在或已被删除，请刷新列表后重试。");
  }
  if (response.status === 422) {
    throw new Error("输入不符合要求，请检查标题和正文长度。");
  }
  if (!response.ok) {
    throw new Error(`请求失败（HTTP ${response.status}），请稍后重试。`);
  }
  if (response.status !== expectedStatus) {
    throw new Error(`服务返回了未预期的状态（HTTP ${response.status}），请稍后重试。`);
  }
  if (expectedStatus === 204) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("服务返回的数据无法读取，请稍后重试。");
  }
}

export function listNotes(): Promise<Note[]> {
  return request<Note[]>("/api/notes", 200);
}

export function createNote(input: NoteInput): Promise<Note> {
  return request<Note>("/api/notes", 201, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateNote(id: number, input: NoteInput): Promise<Note> {
  return request<Note>(`/api/notes/${id}`, 200, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function deleteNote(id: number): Promise<void> {
  return request<void>(`/api/notes/${id}`, 204, { method: "DELETE" });
}
