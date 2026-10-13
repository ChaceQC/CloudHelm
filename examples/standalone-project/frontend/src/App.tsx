import { useCallback, useEffect, useState, type FormEvent } from "react";
import { createNote, deleteNote, listNotes, updateNote, type Note } from "./api";

type LoadState = "loading" | "ready" | "error";

function App() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const titleLength = Array.from(title).length;
  const bodyLength = Array.from(body).length;

  const load = useCallback(async () => {
    setLoadState("loading");
    setLoadError("");
    try {
      setNotes(await listNotes());
      setLoadState("ready");
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : "载入便签失败，请重试。");
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function startEditing(note: Note) {
    setEditingId(note.id);
    setTitle(note.title);
    setBody(note.body);
    setError("");
    setNotice("");
  }

  function resetForm() {
    setEditingId(null);
    setTitle("");
    setBody("");
    setError("");
    setNotice("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanTitle = title.trim();
    const cleanTitleLength = Array.from(cleanTitle).length;
    if (cleanTitleLength === 0) {
      setError("请填写标题。");
      setNotice("");
      return;
    }
    if (cleanTitleLength > 120) {
      setError("标题最多 120 个字符。");
      setNotice("");
      return;
    }
    if (bodyLength > 4000) {
      setError("正文最多 4000 个字符。");
      setNotice("");
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (editingId === null) {
        const created = await createNote({ title: cleanTitle, body });
        setNotes((current) => [...current, created].sort((a, b) => a.id - b.id));
        setNotice("便签已新增。");
        setTitle("");
        setBody("");
      } else {
        const updated = await updateNote(editingId, { title: cleanTitle, body });
        setNotes((current) => current.map((note) => note.id === updated.id ? updated : note));
        setNotice("便签已保存。");
        setEditingId(null);
        setTitle("");
        setBody("");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存便签失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  async function remove(note: Note) {
    setDeletingId(note.id);
    setError("");
    setNotice("");
    try {
      await deleteNote(note.id);
      setNotes((current) => current.filter((item) => item.id !== note.id));
      if (editingId === note.id) resetForm();
      setNotice("便签已删除。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除便签失败，请重试。");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <p className="eyebrow">独立项目参照</p>
        <h1>便签</h1>
        <p className="intro">记录简短想法，支持新增、编辑和删除。</p>
      </header>

      <section className="panel" aria-labelledby="form-heading">
        <div className="section-heading">
          <h2 id="form-heading">{editingId === null ? "新增便签" : "编辑便签"}</h2>
          {editingId !== null && (
            <button className="button button-quiet" type="button" onClick={resetForm} disabled={saving}>
              取消编辑
            </button>
          )}
        </div>
        <form onSubmit={submit}>
          <label htmlFor="note-title">标题</label>
          <input
            id="note-title"
            name="title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            autoComplete="off"
            disabled={saving}
          />
          <div className="field-meta"><span>最多 120 个字符</span><span>{titleLength}/120</span></div>

          <label htmlFor="note-body">正文</label>
          <textarea
            id="note-body"
            name="body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={5}
            disabled={saving}
          />
          <div className="field-meta"><span>最多 4000 个字符</span><span>{bodyLength}/4000</span></div>

          {error && <p className="message message-error" role="alert">{error}</p>}
          {notice && <p className="message message-success" role="status">{notice}</p>}
          <button className="button button-primary" type="submit" disabled={saving || deletingId !== null || loadState !== "ready"}>
            {saving ? "正在保存…" : editingId === null ? "新增便签" : "保存修改"}
          </button>
        </form>
      </section>

      <section className="notes-section" aria-labelledby="notes-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">你的记录</p>
            <h2 id="notes-heading">便签列表</h2>
          </div>
          {loadState === "ready" && <span className="count">{notes.length} 条</span>}
        </div>

        {loadState === "loading" && <p className="message" role="status">正在载入便签…</p>}
        {loadState === "error" && (
          <div className="message message-error" role="alert">
            <p>{loadError}</p>
            <button className="button button-quiet" type="button" onClick={() => void load()}>重新载入</button>
          </div>
        )}
        {loadState === "ready" && notes.length === 0 && (
          <div className="empty-state"><p>还没有便签，使用上方表单新增一条。</p></div>
        )}
        {loadState === "ready" && notes.length > 0 && (
          <ul className="note-list">
            {notes.map((note) => (
              <li className="note-card" key={note.id}>
                <div className="note-content">
                  <h3>{note.title}</h3>
                  <p className="note-body">{note.body || <span className="muted">（无正文）</span>}</p>
                </div>
                <div className="note-actions">
                  <button className="button button-quiet" type="button" onClick={() => startEditing(note)} disabled={saving || deletingId !== null}>
                    编辑
                  </button>
                  <button
                    className="button button-danger"
                    type="button"
                    onClick={() => void remove(note)}
                    disabled={saving || deletingId !== null}
                    aria-label={`删除便签：${note.title}`}
                  >
                    {deletingId === note.id ? "正在删除…" : "删除"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

export default App;
