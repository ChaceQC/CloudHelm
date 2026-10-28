import { useEffect, useRef, useState } from "react";
import { codeOf, sessionChanged, taskPath } from "./api";
import type { AgentDiff, AgentView, Task } from "./types";
import type { Hub } from "./useHub";
import { Facts, JsonView, Status } from "./ui";

export function AgentPanel({ hub, task }: { hub: Hub; task: Task }) {
  const projectId = hub.snapshot?.project.project_id ?? "";
  const identity = hub.identity?.session_id ?? "";
  const captured = hub.snapshot?.captured_at ?? "";
  const canRead = !!hub.snapshot?.available_actions.includes("operation.query");
  const scope = JSON.stringify([identity, projectId, task.task_id]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const agentQuery = useRef(0);
  const diffQuery = useRef(0);
  const [agent, setAgent] = useState<{ scope: string; captured: string; value: AgentView } | null>(null);
  const [diff, setDiff] = useState<{ scope: string; captured: string; value: AgentDiff } | null>(null);
  const [loading, setLoading] = useState(false);
  const [diffLoading, setDiffLoading] = useState(false);
  const [error, setError] = useState("");
  const [diffError, setDiffError] = useState("");
  const route = taskPath(task.task_id);
  const version = { expected_version: task.version, expected_control_revision: task.control_revision,
    expected_input_validity_revision: task.input_validity_revision };
  const currentAgent = canRead && agent?.scope === scope && agent.captured === captured ? agent.value : null;
  const currentDiff = canRead && diff?.scope === scope && diff.captured === captured ? diff.value : null;
  const canAdvance = hub.can("task.command") && hub.can("workspace.write") && task.declaration.budget.currency === "USD"
    && task.state === "active" && task.input_status === "valid"
    && !task.ordinary_progress_closed && !task.cancellation && !!currentAgent && !loading && !error;

  const loadAgent = () => {
    const request = ++agentQuery.current;
    setLoading(true); setError("");
    void hub.query<AgentView>(`${route}/agent`).then(value => {
      if (scopeRef.current === scope && agentQuery.current === request) setAgent({ scope, captured, value });
    }).catch(reason => {
      if (scopeRef.current === scope && agentQuery.current === request && !sessionChanged(reason)) setError(codeOf(reason));
    }).finally(() => {
      if (scopeRef.current === scope && agentQuery.current === request) setLoading(false);
    });
  };
  const loadDiff = (workItemId: string) => {
    const request = ++diffQuery.current;
    setDiff(null); setDiffLoading(true); setDiffError("");
    void hub.query<AgentDiff>(`${route}/agent-diff/${encodeURIComponent(workItemId)}`).then(value => {
      if (scopeRef.current === scope && diffQuery.current === request) setDiff({ scope, captured, value });
    }).catch(reason => {
      if (scopeRef.current === scope && diffQuery.current === request && !sessionChanged(reason)) setDiffError(codeOf(reason));
    }).finally(() => {
      if (scopeRef.current === scope && diffQuery.current === request) setDiffLoading(false);
    });
  };
  useEffect(() => {
    setAgent(null); setDiff(null); setError(""); setDiffError(""); setLoading(false); setDiffLoading(false);
    return () => { ++agentQuery.current; ++diffQuery.current; };
  }, [scope]);
  useEffect(() => {
    if (identity && projectId && captured && canRead) loadAgent();
    else { setAgent(null); setDiff(null); }
    return () => { ++agentQuery.current; };
  }, [scope, captured, canRead]);

  return <section><div className="section-title"><h3>Agent 推进</h3>
    <button type="button" disabled={!identity || !projectId || !canRead || loading} onClick={loadAgent}>查询 Agent 状态</button></div>
    {!canRead && <p className="muted">当前权限不能读取 Agent 操作结果。</p>}
    {!hub.snapshot?.available_actions.includes("workspace.write") && <p className="muted">开发推进需要项目工作区写入权限。</p>}
    <p className="muted">命令回执表示已接收；Run 结果与 Task 完成分别判断。长操作等待后由服务端沿原操作续接。</p>
    {task.declaration.budget.currency !== "USD" && <p className="notice">当前模型与计费只支持 USD 预算的 Task。</p>}
    {loading && <p className="muted">正在查询 Agent 状态…</p>}
    {error && <p className="error">Agent 状态查询：{error}</p>}
    {currentAgent?.truncated && <p className="notice">Agent 结果已截断，仅显示服务端返回的有界事实。</p>}
    <form onSubmit={e => {
      e.preventDefault();
      const form = new FormData(e.currentTarget);
      hub.command(`${route}/agent-runs`, { ...version, work_item_id: String(form.get("work_item")),
        max_requests: Number(form.get("max_requests")), max_duration_seconds: Number(form.get("max_duration_seconds")),
        max_output_tokens: Number(form.get("max_output_tokens")), per_request_cost_upper_bound: String(form.get("cost")) });
    }}><h4>启动新 Session</h4>
      <label>工作项<select name="work_item" defaultValue="" required>
        <option value="" disabled>选择工作项</option>
        {task.work_items.map(item => <option key={item.work_item_id} value={item.work_item_id}>
          {item.goal} · {item.state} · {item.work_item_id}</option>)}
      </select></label>
      <div className="form-row"><label>请求上限<input name="max_requests" type="number" min="1" max="12" step="1" defaultValue="3" required/></label>
        <label>时长上限（秒）<input name="max_duration_seconds" type="number" min="1" max="86400" step="1" defaultValue="60" required/></label>
        <label>输出 Token 上限<input name="max_output_tokens" type="number" min="1" max="128000" step="1" defaultValue="4096" required/></label></div>
      <label>单次请求预留上限（{task.declaration.budget.currency}）<input name="cost" defaultValue="0.1" required
        inputMode="decimal" pattern="(0|[1-9][0-9]{0,15})(\.[0-9]{1,8})?"/></label>
      <p className="muted">每次请求的预留金额由你填写，实际准入仍受 Task 预算限制。</p>
      <button className="primary" disabled={!canAdvance || !task.work_items.length}>启动 Agent Run</button>
    </form>
    {currentAgent && !currentAgent.sessions.length && <p className="muted">当前没有 Agent Session。</p>}
    {currentAgent?.sessions.map(session => {
      const waiting = session.runs.some(run => run.waits.some(wait => wait.state === "waiting" && !wait.continuation_run_id));
      const active = ["queued", "running"].includes(session.state)
        || session.runs.some(run => ["queued", "running"].includes(run.state));
      return <div className="query-result" key={session.session_id}>
        <div className="section-title"><h4>Session · {session.session_id}</h4><Status value={session.state}/></div>
        <Facts values={{ "Session 版本": session.version, "工作项": session.work_item_id,
          "请求上限": session.policy.max_requests, "时长上限": `${session.policy.max_duration_seconds} 秒`,
          "输出 Token 上限": session.policy.max_output_tokens,
          "单次预留上限": `${session.policy.per_request_cost_upper_bound} ${task.declaration.budget.currency}` }}/>
        {waiting && <p className="notice">等待原操作结果；服务端将在条件满足后沿原等待续接。</p>}
        <button type="button" disabled={!canAdvance || active || waiting} onClick={() => hub.command(`${route}/agent-runs`, {
          ...version, work_item_id: session.work_item_id, session_id: session.session_id, expected_session_version: session.version,
        })}>按原策略继续 Session</button>
        <button type="button" disabled={!identity || !projectId || !canRead || diffLoading}
          onClick={() => loadDiff(session.work_item_id)}>查询该工作项差异</button>
        {session.runs.map(run => <details className="json" key={run.run_id}>
          <summary>Run · {run.run_id} · {run.state}</summary>
          <Status value={run.state}/><Facts values={{ "请求次数": run.request_count,
            "预留金额": `${run.reserved_cost} ${task.declaration.budget.currency}`, "创建时间": run.created_at,
            "开始时间": run.started_at, "截止时间": run.deadline_at }}/>
          {run.result ? <JsonView value={run.result} title="Run 结果与交接事实"/> : <p className="muted">尚未取得 Run 结果。</p>}
          {run.tool_results.map(tool => <JsonView key={tool.tool_call_id} value={tool.result}
            title={`工具反馈 · ${tool.tool_name} · ${tool.tool_call_id}`}/>)}
          {run.requests.map(request => <div key={request.request_record_id}><strong>模型请求 · {request.request_record_id}</strong>
            <Status value={request.state}/><Facts values={{ "预留金额": `${request.reserved_cost} ${task.declaration.budget.currency}`,
              "计算费用": request.calculated_cost == null ? "unknown · 待核对" : `${request.calculated_cost} ${task.declaration.budget.currency}`,
              "账单金额": request.billed_amount == null ? "unknown · 待核对" : `${request.billed_amount} ${request.billed_currency ?? ""}` }}/></div>)}
          {run.waits.map(wait => <div key={wait.wait_condition_id}><strong>等待条件 · {wait.wait_condition_id}</strong>
            <Status value={wait.state}/><Facts values={{ "原操作": wait.operation_id, "续接 Run": wait.continuation_run_id }}/></div>)}
        </details>)}
      </div>;
    })}
    {diffLoading && <p className="muted">正在查询工作区差异…</p>}
    {diffError && <p className="error">差异查询：{diffError}</p>}
    {currentDiff && <div><Facts values={{ "工作区": currentDiff.workspace_id, "工作项": currentDiff.work_item_id }}/>
      {currentDiff.truncated && <p className="notice">差异列表已截断。</p>}
      {!currentDiff.files.length && <p className="muted">本次查询没有返回文件差异。</p>}
      {currentDiff.files.map(file => <details className="json" key={file.path}>
        <summary>{file.path}{file.binary ? " · 二进制" : ""}{file.truncated ? " · 已截断" : ""}</summary>
        {file.reason_code && <p>{file.reason_code}</p>}{file.patch !== null && <pre>{file.patch}</pre>}
      </details>)}
    </div>}
  </section>;
}
