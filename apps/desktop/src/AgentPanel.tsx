import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { AgentRunDetail, AgentSummary } from "./agent-contract.generated";
import { AgentRunFacts, AgentWaitFacts, AgentWorkItemFacts } from "./AgentFacts";
import { codeOf, sessionChanged, taskPath } from "./api";
import type { AgentDiff, Task } from "./types";
import type { Hub } from "./useHub";
import { Facts, Status } from "./ui";

type QueryScope = { generation: Hub["generation"]; snapshot: Hub["snapshot"]; taskId: string };
type QueryResult<T> = { scope: QueryScope; route: string; loading: boolean; value?: T; error?: string };

function useAgentQuery<T>(scope: QueryScope, query: Hub["query"]) {
  const currentScope = useRef<QueryScope | null>(null);
  const sequence = useRef(0);
  const [result, setResult] = useState<QueryResult<T> | null>(null);
  useLayoutEffect(() => {
    currentScope.current = scope;
    return () => { currentScope.current = null; };
  }, [scope]);

  const load = (route: string) => {
    const request = ++sequence.current;
    const isCurrent = () => currentScope.current === scope && sequence.current === request;
    setResult({ scope, route, loading: true });
    void query<T>(route, isCurrent).then(value => {
      if (isCurrent()) setResult({ scope, route, loading: false, value });
    }, reason => {
      if (isCurrent()) setResult({ scope, route, loading: false,
        error: sessionChanged(reason) ? undefined : codeOf(reason) });
    });
  };
  const close = () => { ++sequence.current; setResult(null); };
  return { load, close, current: result?.scope === scope ? result : null };
}

export function AgentPanel({ hub, task }: { hub: Hub; task: Task }) {
  const { snapshot, generation } = hub;
  const taskId = task.task_id;
  // Each snapshot binds the project, stream, permission revision and capture time together.
  const scope = useMemo(() => ({ generation, snapshot, taskId }), [generation, snapshot, taskId]);
  const canRead = !!snapshot?.available_actions.includes("operation.query")
    && snapshot.available_actions.includes("resource.read");
  const canQuery = !!generation && canRead;
  const summary = useAgentQuery<AgentSummary>(scope, hub.query);
  const detail = useAgentQuery<AgentRunDetail>(scope, hub.query);
  const diff = useAgentQuery<AgentDiff>(scope, hub.query);
  const route = taskPath(taskId);
  const summaryRoute = `${route}/agent-summary`;
  const runRoute = `${route}/agent-runs`;
  const currentAgent = summary.current?.value;
  const currentDiff = diff.current?.value;
  const currency = task.declaration.budget.currency;
  const version = { expected_version: task.version, expected_control_revision: task.control_revision,
    expected_input_validity_revision: task.input_validity_revision };
  const canAdvance = hub.can("task.command") && hub.can("workspace.write") && currency === "USD"
    && task.state === "active" && task.input_status === "valid"
    && !task.ordinary_progress_closed && !task.cancellation && !!currentAgent;

  useEffect(() => {
    if (canQuery) summary.load(summaryRoute);
  }, [scope, canQuery]);

  return <section><div className="section-title"><h3>Agent 推进</h3>
    <button type="button" disabled={!canQuery || summary.current?.loading} onClick={() => {
      detail.close(); summary.load(summaryRoute);
    }}>查询 Agent 状态</button></div>
    {!canRead && <p className="muted">当前权限不能读取 Agent 操作结果。</p>}
    {!snapshot?.available_actions.includes("workspace.write") && <p className="muted">开发推进需要项目工作区写入权限。</p>}
    <p className="muted">命令回执表示已接收；Run 结果与 Task 完成分别判断。长操作等待后由服务端沿原操作续接。</p>
    {currency !== "USD" && <p className="notice">当前模型与计费只支持 USD 预算的 Task。</p>}
    {summary.current?.loading && <p className="muted">正在查询 Agent 状态…</p>}
    {summary.current?.error && <p className="error">Agent 状态查询：{summary.current.error}</p>}
    {currentAgent?.truncated && <p className="notice">Agent 摘要已截断，部分工作项、Session、Run 或等待可能未列出。</p>}
    {currentAgent && <section><h4>可见工作项与能力</h4>
      {!currentAgent.work_items.length && <p className="muted">当前没有可见工作项。</p>}
      {currentAgent.work_items.map(item => <AgentWorkItemFacts key={item.work_item_id} item={item}/>)}
    </section>}
    <form onSubmit={e => {
      e.preventDefault();
      const form = new FormData(e.currentTarget);
      hub.command(runRoute, { ...version, work_item_id: String(form.get("work_item")),
        max_requests: Number(form.get("max_requests")), max_duration_seconds: Number(form.get("max_duration_seconds")),
        max_output_tokens: Number(form.get("max_output_tokens")), per_request_cost_upper_bound: String(form.get("cost")) });
    }}><h4>启动新 Session</h4>
      <label>工作项<select name="work_item" defaultValue="" required>
        <option value="" disabled>选择工作项</option>
        {currentAgent?.work_items.map(item => <option key={item.work_item_id} value={item.work_item_id}>
          {item.goal} · {item.state} · {item.work_item_id}</option>)}
      </select></label>
      <div className="form-row"><label>请求上限<input name="max_requests" type="number" min="1" max="12" step="1" defaultValue="3" required/></label>
        <label>时长上限（秒）<input name="max_duration_seconds" type="number" min="1" max="86400" step="1" defaultValue="60" required/></label>
        <label>输出 Token 上限<input name="max_output_tokens" type="number" min="1" max="128000" step="1" defaultValue="4096" required/></label></div>
      <label>单次请求预留上限（{currency}）<input name="cost" defaultValue="0.1" required
        inputMode="decimal" pattern="(0|[1-9][0-9]{0,15})(\.[0-9]{1,8})?"/></label>
      <p className="muted">每次请求的预留金额由你填写，实际准入仍受 Task 预算限制。</p>
      <button className="primary" disabled={!canAdvance || !currentAgent?.work_items.length}>启动 Agent Run</button>
    </form>
    {currentAgent && <section><h4>已列 Run 的模型费用</h4><Facts values={{
      "已知计算费用小计": currentAgent.fees.known_calculated_cost === null ? "暂无已知金额"
        : `${currentAgent.fees.known_calculated_cost} ${currentAgent.fees.currency}`,
      "费用未知的请求数": currentAgent.fees.unknown_request_count,
      "未知请求的预留金额": `${currentAgent.fees.unknown_reserved_cost} ${currentAgent.fees.currency}`,
    }}/></section>}
    {!!currentAgent?.waits.length && <section><h4>Task 尚未续接的等待</h4>
      {currentAgent.waits.map(wait => <AgentWaitFacts key={wait.wait_condition_id} wait={wait}/>)}
    </section>}
    {currentAgent && !currentAgent.sessions.length && <p className="muted">当前没有 Agent Session。</p>}
    {currentAgent?.sessions.map(session => {
      const { policy, work_item_id: workItemId } = session;
      const waiting = currentAgent.waits.some(wait => session.runs.some(run => run.run_id === wait.from_run_id));
      const active = ["queued", "running"].includes(session.state)
        || session.runs.some(run => ["queued", "running"].includes(run.state));
      return <div className="query-result" key={session.session_id}>
        <div className="section-title"><h4>Session · {session.session_id}</h4><Status value={session.state}/></div>
        <Facts values={{ "Session 版本": session.version, "工作项": workItemId,
          ...(policy && { "角色": policy.role, "请求上限": policy.max_requests,
            "时长上限": `${policy.max_duration_seconds} 秒`, "输出 Token 上限": policy.max_output_tokens,
            "单次预留上限": `${policy.per_request_cost_upper_bound} ${currency}` }) }}/>
        {waiting && <p className="notice">原等待尚未续接，服务端将在条件满足后处理。</p>}
        {workItemId && <div className="actions">
          <button type="button" disabled={!canAdvance || !policy || active || waiting} onClick={() => hub.command(runRoute, {
            ...version, work_item_id: workItemId, session_id: session.session_id, expected_session_version: session.version,
          })}>按原策略继续 Session</button>
          <button type="button" disabled={!canQuery || diff.current?.loading}
            onClick={() => diff.load(`${route}/agent-diff/${encodeURIComponent(workItemId)}`)}>查询该工作项差异</button>
        </div>}
        {session.runs.map(run => {
          const path = `${runRoute}/${encodeURIComponent(run.run_id)}`;
          const opened = detail.current?.route === path;
          return <details className="json" key={run.run_id} open={opened}>
            <summary onClick={e => {
              e.preventDefault();
              if (opened) detail.close();
              else detail.load(path);
            }}>Run · {run.run_id} · {run.state}</summary>
            {opened && detail.current?.loading && <p className="muted">正在查询 Run 详情…</p>}
            {opened && detail.current?.error && <p className="error">Run 详情查询：{detail.current.error}</p>}
            {opened && detail.current?.value && <AgentRunFacts run={detail.current.value} currency={currency}/>}
          </details>;
        })}
      </div>;
    })}
    {diff.current?.loading && <p className="muted">正在查询工作区差异…</p>}
    {diff.current?.error && <p className="error">差异查询：{diff.current.error}</p>}
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
