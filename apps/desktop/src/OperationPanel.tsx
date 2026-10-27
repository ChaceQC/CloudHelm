import { useState } from "react";
import { codeOf, objectPath, taskPath } from "./api";
import type { Hub } from "./useHub";
import type { Json } from "./types";
import { JsonView, Status } from "./ui";

export function OperationPanel({ hub, taskId }: { hub: Hub; taskId: string }) {
  const [kind, setKind] = useState("build");
  const [owner, setOwner] = useState(taskId);
  const [operation, setOperation] = useState("");
  const [result, setResult] = useState<Json | null>(null);
  const [error, setError] = useState("");
  return <section className="card operation-panel"><h2>查询原操作</h2><form onSubmit={e => {
    e.preventDefault(); setError(""); setResult(null);
    const project = hub.snapshot?.project.project_id;
    if (!project) return;
    const id = encodeURIComponent(operation.trim());
    const route = kind === "build" ? `${taskPath(owner.trim())}/builds/${id}`
      : kind === "workspace" ? `/api/workspaces/${encodeURIComponent(owner.trim())}/operations/${id}`
      : kind === "development" ? `/api/development-environments/${encodeURIComponent(owner.trim())}/operations/${id}`
      : objectPath(project, kind === "source" ? "source-imports" : "deployment-plans", operation.trim());
    void hub.query<Json>(route).then(setResult).catch(reason => setError(codeOf(reason)));
  }}><div className="form-row"><label>操作类型<select value={kind} onChange={e => { setKind(e.target.value); setResult(null); }}>
    <option value="build">构建</option><option value="workspace">工作区操作</option><option value="development">开发环境操作</option>
    <option value="source">源码导入</option><option value="deployment">部署（按计划 ID）</option></select></label>
    {["build", "workspace", "development"].includes(kind) && <label>{kind === "build" ? "Task ID" : kind === "workspace" ? "Workspace ID" : "开发环境 ID"}
      <input value={owner} onChange={e => setOwner(e.target.value)} required maxLength={160}/></label>}
    <label>{kind === "deployment" ? "Plan ID" : "原 Operation ID"}<input value={operation} onChange={e => setOperation(e.target.value)} required maxLength={160}/></label>
    <button disabled={!hub.snapshot}>查询</button></div></form>
    {error && <p className="error">{error}</p>}{result && <div className="query-result">
      <Status value={String(result.state ?? result.status ?? "observed")}/>
      <JsonView value={result} title="原身份的业务与物理事实"/></div>}
  </section>;
}
