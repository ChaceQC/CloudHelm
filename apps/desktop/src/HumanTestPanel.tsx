import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { codeOf, sessionChanged, taskPath } from "./api";
import type { HumanTestEnvironment, HumanTestOptions, HumanTestSession, Task } from "./types";
import type { Hub } from "./useHub";
import { Facts, Status } from "./ui";

const states: Record<HumanTestSession["state"], string> = {
  preparing: "准备中 / 可能排队", awaiting_human: "等待指定测试者", testing: "人工测试中",
  completed: "已记录结论", expired: "已到期", cancelled: "已取消",
};
const conclusions = { passed: "通过", changes_requested: "需要修改", skipped: "跳过 · 未完成人工验证" };
const sessionPath = (id: string) => `/api/human-tests/${encodeURIComponent(id)}`;
const taskGuard = (task: Task) => ({ expected_version: task.version, expected_control_revision: task.control_revision,
  expected_input_validity_revision: task.input_validity_revision });
const deadlineAfter = (ready: string | null, hours: number) =>
  ready ? new Date(Date.parse(ready) + hours * 3600000).toISOString() : null;

function HumanTestRound({ hub, task, session, latest, fresh }: {
  hub: Hub; task: Task; session: HumanTestSession; latest: boolean; fresh: boolean;
}) {
  const [environment, setEnvironment] = useState<HumanTestEnvironment | null>(null);
  const [environmentError, setEnvironmentError] = useState("");
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [choice, setChoice] = useState<"" | "passed" | "changes_requested" | "skipped">("");
  const [summary, setSummary] = useState("");
  const [steps, setSteps] = useState("");
  const [expected, setExpected] = useState("");
  const [actual, setActual] = useState("");
  const [skipReason, setSkipReason] = useState("");
  const query = useRef(0);
  const scope = JSON.stringify([hub.identity?.session_id, session.session_id, session.revision, session.environment_id]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  useEffect(() => {
    setEnvironment(null); setEnvironmentError(""); setLoading(false); setOpening(false);
    return () => { ++query.current; };
  }, [scope]);

  const loadEnvironment = () => {
    if (!session.environment_id) return;
    const request = ++query.current;
    setLoading(true);
    void hub.query<HumanTestEnvironment>(`/api/preview-environments/${encodeURIComponent(session.environment_id)}`)
      .then(value => {
        if (scopeRef.current === scope && query.current === request) { setEnvironment(value); setEnvironmentError(""); }
      }).catch(reason => {
        if (scopeRef.current === scope && query.current === request && !sessionChanged(reason)) setEnvironmentError(codeOf(reason));
      }).finally(() => {
        if (scopeRef.current === scope && query.current === request) setLoading(false);
      });
  };
  const assigned = hub.identity?.user_id === session.tester.subject_id;
  const current = latest && fresh && hub.writable && task.version >= session.task_version;
  const active = session.state === "awaiting_human" || session.state === "testing";
  const controllable = session.state === "preparing" || active;
  const guard = { ...taskGuard(task), expected_session_revision: session.revision };
  const route = sessionPath(session.session_id);
  const canEnter = current && assigned && hub.can("human_test.enter");
  const conclusionAction = choice === "passed" ? "human_test.pass"
    : choice === "changes_requested" ? "human_test.request_changes" : "human_test.skip";
  const canConclude = current && assigned && !!choice && hub.can(conclusionAction)
    && (active || (choice === "skipped" && !!session.ready_at && ["expired", "cancelled"].includes(session.state)))
    && (choice !== "skipped" || (session.policy.skip_allowed && !!skipReason.trim()))
    && (choice !== "changes_requested" || !!summary.trim())
    && (!(steps.trim() || expected.trim() || actual.trim()) || !!summary.trim());
  const revocation = environment?.revocation_status;
  const revocationLabel = revocation === "effective" ? "已确认" : revocation === "pending" ? "撤销待确认"
    : revocation === "pending_time_unknown" ? "撤销待确认 · 时间未知" : revocation ?? "尚未确认";

  return <div className="query-result">
    <div className="section-title"><h4>轮次 · {session.round_id}</h4><Status value={session.state}/></div>
    <p>{states[session.state]}{!latest && " · 历史轮次，只读"}</p>
    <Facts values={{ "测试 Session": session.session_id, "测试者": session.tester.subject_id,
      "固定候选": session.candidate_id, "候选修订": session.candidate_ref.revision,
      "固定输入修订": session.final_input_set_ref.revision, "测试配置修订": session.test_config_ref.revision,
      "数据集修订": session.dataset_ref.revision, "策略修订": session.policy_ref.revision,
      "会话修订": session.revision, "绑定 Task 版本": session.task_version,
      "绑定控制修订": session.control_revision, "绑定输入修订": session.input_validity_revision,
      "环境实例": session.environment_id, "准备或排队原因": session.preparation_reason,
      "就绪时间 UTC": session.ready_at, "初始期限 UTC": deadlineAfter(session.ready_at, 4),
      "当前期限 UTC": session.expires_at, "最长期限 UTC": deadlineAfter(session.ready_at, 6),
      "最近人类活动 UTC": session.last_human_activity_at, "空闲提醒 UTC": session.idle_warning_at,
      "续期时间 UTC": session.renewed_at,
      "完成门槛": session.policy.is_completion_gate ? "纳入" : "不纳入", "允许跳过": session.policy.skip_allowed ? "是" : "否" }}/>
    <p className="muted">连续 30 分钟没有人类有效活动会提醒，宽限 5 分钟；自动探测和后台心跳不算活动。续期需再次获得授权及容量准入。</p>
    {!assigned && <p className="muted">只有指定测试者能记录活动、续期和提交人工结论。</p>}
    <div className="actions">
      <button type="button" disabled={!canEnter || session.state !== "preparing"}
        onClick={() => hub.command(`${route}/ready`, guard)}>确认环境就绪</button>
      <button type="button" disabled={!canEnter || !active}
        onClick={() => hub.command(`${route}/activity`, guard)}>记录实际人类活动</button>
      <button type="button" disabled={!canEnter || !active || !!session.renewed_at}
        onClick={() => hub.command(`${route}/renew`, guard)}>申请一次续期</button>
      <button type="button" disabled={!canEnter || !controllable}
        onClick={() => hub.command(`${route}/yield`, guard)}>让出资源</button>
      <button type="button" className="danger" disabled={!current || !controllable || !(canEnter || hub.can("task.command"))}
        onClick={() => hub.command(`${route}/cancel`, guard)}>取消人测</button>
    </div>
    <p className="muted">就绪、停止和取消均以服务端事实为准；让出或取消不表示访问撤销和进程停止已确认。</p>
    <div className="actions"><button type="button" disabled={!session.environment_id || !hub.can("resource.read") || loading}
      onClick={loadEnvironment}>查询实际环境与撤销状态</button></div>
    {loading && <p className="muted">正在查询环境事实…</p>}
    {environmentError && <p className="error">环境查询：{environmentError}</p>}
    {environment ? <Facts values={{ "环境状态": environment.state, "实际运行修订": environment.actual_revision ?? "尚未确认",
      "资源占账": environment.resource_reservation_id, "环境期限 UTC": environment.expires_at,
      "环境原因": environment.reason, "访问撤销确认": revocationLabel }}/>
      : <p className="notice">实际运行修订和访问撤销确认尚未取得；需要时显式查询，不能由 Session 状态推断。</p>}
    {environment?.management_start_url && <p className="muted">在受信管理端打开资源查询地址：
      <code>{environment.management_start_url}</code></p>}
    {environment?.client_route === "tauri_windows_webview2" && environment.state === "ready" &&
      <button type="button" disabled={!hub.generation || !canEnter || opening} onClick={() => {
        const generation = hub.generation;
        const expectedScope = scope;
        if (!generation) return;
        setOpening(true);
        void invoke<string>("preview_open", { generation, environmentId: environment.environment_id })
          .catch(reason => {
            if (scopeRef.current === expectedScope) setEnvironmentError(codeOf(reason));
          }).finally(() => {
            if (scopeRef.current === expectedScope) setOpening(false);
          });
      }}>{opening ? "正在打开预览…" : "打开隔离预览"}</button>}
    {session.conclusion && <Facts values={{ "人工结论": conclusions[session.conclusion.conclusion],
      "结论提交者": session.conclusion.concluded_by.subject_id, "提交时间 UTC": session.conclusion.concluded_at_utc,
      "跳过原因": session.conclusion.skip_reason, "反馈摘要": session.feedback?.summary,
      "操作步骤": session.feedback?.steps, "预期结果": session.feedback?.expected,
      "实际结果": session.feedback?.actual
    }}/>}
    {!session.conclusion && latest && <form onSubmit={e => {
      e.preventDefault();
      if (!canConclude || !choice) return;
      const feedback = summary.trim() ? { summary: summary.trim(), steps: steps.trim() || null,
        expected: expected.trim() || null, actual: actual.trim() || null, attachment_refs: [] } : null;
      hub.command(`${route}/conclusion`, { ...guard, conclusion: choice, feedback,
        skip_reason: choice === "skipped" ? skipReason.trim() : null });
    }}>
      <h4>提交人工结论</h4>
      <p className="muted">仅由指定测试者按实际情况选择。提交内容会进入本机命令日志，请勿输入凭据、密钥或敏感数据。</p>
      <label>结论<select value={choice} onChange={e => setChoice(e.target.value as typeof choice)}>
        <option value="">请选择</option><option value="passed">通过</option>
        <option value="changes_requested">需要修改</option><option value="skipped" disabled={!session.policy.skip_allowed}>跳过</option>
      </select></label>
      {choice === "skipped" && <label>跳过原因<input value={skipReason} onChange={e => setSkipReason(e.target.value)} maxLength={160} required/></label>}
      <label>反馈摘要{choice === "changes_requested" || steps.trim() || expected.trim() || actual.trim() ? "（必填）" : "（可选）"}
        <textarea value={summary} onChange={e => setSummary(e.target.value)} maxLength={4096}
          required={choice === "changes_requested" || !!(steps.trim() || expected.trim() || actual.trim())}/></label>
      <label>操作步骤<textarea value={steps} onChange={e => setSteps(e.target.value)} maxLength={8192}/></label>
      <div className="form-row"><label>预期结果<textarea value={expected} onChange={e => setExpected(e.target.value)} maxLength={4096}/></label>
        <label>实际结果<textarea value={actual} onChange={e => setActual(e.target.value)} maxLength={4096}/></label></div>
      <button className="primary" disabled={!canConclude}>提交所选结论</button>
    </form>}
  </div>;
}

export function HumanTestPanel({ hub, task }: { hub: Hub; task: Task }) {
  const identity = hub.identity?.session_id ?? "";
  const project = hub.snapshot?.project.project_id ?? "";
  const captured = hub.snapshot?.captured_at ?? "";
  const canRead = !!hub.snapshot?.available_actions.includes("resource.read");
  const scope = JSON.stringify([identity, project, task.task_id]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const optionScope = JSON.stringify([scope, task.version, task.control_revision, task.input_validity_revision]);
  const optionScopeRef = useRef(optionScope);
  optionScopeRef.current = optionScope;
  const sessionQuery = useRef(0);
  const optionsQuery = useRef(0);
  const wasBusy = useRef(false);
  const [sessions, setSessions] = useState<{ scope: string; captured: string; value: HumanTestSession[] } | null>(null);
  const [options, setOptions] = useState<{ scope: string; value: HumanTestOptions } | null>(null);
  const [open, setOpen] = useState(false);
  const [candidate, setCandidate] = useState("");
  const [loading, setLoading] = useState(false);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [error, setError] = useState("");
  const [optionsError, setOptionsError] = useState("");
  const route = taskPath(task.task_id);
  const current = canRead && sessions?.scope === scope ? sessions.value : null;
  const currentOptions = options?.scope === optionScope ? options.value : null;
  const selected = currentOptions?.candidates.find(item => item.candidate_id === candidate);
  const active = current?.some(item => ["preparing", "awaiting_human", "testing"].includes(item.state));
  const freshSessions = sessions?.scope === scope && sessions.captured === captured && !loading && !error;
  const canStart = hub.can("task.command") && !!current && freshSessions && !active
    && (task.state === "active" && !task.ordinary_progress_closed || task.state === "completed")
    && task.input_status === "valid" && !task.cancellation;
  const loadSessions = () => {
    const request = ++sessionQuery.current;
    setLoading(true);
    void hub.query<HumanTestSession[]>(`${route}/human-tests`).then(value => {
      if (scopeRef.current === scope && sessionQuery.current === request) { setSessions({ scope, captured, value }); setError(""); }
    }).catch(reason => {
      if (scopeRef.current === scope && sessionQuery.current === request && !sessionChanged(reason)) setError(codeOf(reason));
    }).finally(() => {
      if (scopeRef.current === scope && sessionQuery.current === request) setLoading(false);
    });
  };
  const loadOptions = () => {
    const request = ++optionsQuery.current;
    setOptionsLoading(true);
    void hub.query<HumanTestOptions>(`${route}/human-test-options`).then(value => {
      if (optionScopeRef.current === optionScope && optionsQuery.current === request) { setOptions({ scope: optionScope, value }); setOptionsError(""); }
    }).catch(reason => {
      if (optionScopeRef.current === optionScope && optionsQuery.current === request && !sessionChanged(reason)) setOptionsError(codeOf(reason));
    }).finally(() => {
      if (optionScopeRef.current === optionScope && optionsQuery.current === request) setOptionsLoading(false);
    });
  };
  useEffect(() => {
    setSessions(null); setOptions(null); setOpen(false); setCandidate(""); setError(""); setOptionsError("");
    setLoading(false); setOptionsLoading(false);
    return () => { ++sessionQuery.current; ++optionsQuery.current; };
  }, [scope]);
  useEffect(() => {
    if (identity && project && captured && canRead) loadSessions();
    return () => { ++sessionQuery.current; };
  }, [scope, captured, canRead]);
  useEffect(() => {
    ++optionsQuery.current; setOptionsLoading(false); setOptionsError(""); setCandidate("");
  }, [optionScope]);
  useEffect(() => {
    const finished = wasBusy.current && !hub.busy;
    wasBusy.current = hub.busy;
    if (finished && identity && project && canRead) loadSessions();
  }, [hub.busy]);

  return <section><div className="section-title"><h3>可选人工测试</h3>
    <button type="button" disabled={!identity || !project || !canRead || loading} onClick={loadSessions}>查询人工测试</button></div>
    <p className="notice">查询实际环境后，可打开安装方已验证的 Windows 隔离预览；管理端资源查询地址不授予预览访问能力。</p>
    {!canRead && <p className="muted">当前权限不能读取人测事实。</p>}
    {loading && <p className="muted">正在查询人工测试…</p>}
    {error && <p className="error">人工测试查询：{error}</p>}
    {current && !current.length && <p>{freshSessions ? "未执行人工测试" : "人工测试记录待刷新"}</p>}
    <div className="actions"><button type="button" disabled={!canStart || optionsLoading} onClick={() => {
      setOpen(true); loadOptions();
    }}>选择候选并开启</button>{open && <button type="button" onClick={() => setOpen(false)}>收起</button>}</div>
    {open && <form onSubmit={e => {
      e.preventDefault();
      if (!canStart || !selected || !currentOptions || optionsError) return;
      hub.command(`${route}/human-tests`, { ...taskGuard(task), candidate_id: selected.candidate_id,
        tester_id: currentOptions.tester_id, test_config_ref: selected.test_config_ref, dataset_ref: selected.dataset_ref });
    }}><h4>显式申请人工测试</h4>
      {optionsLoading && <p className="muted">正在查询可用候选…</p>}
      {optionsError && <p className="error">候选查询：{optionsError}</p>}
      {!currentOptions && !optionsLoading && !optionsError && <p className="muted">Task 版本已变化，请重新查询可用候选。</p>}
      {currentOptions && <>
        <Facts values={{ "指定测试者": currentOptions.tester_id }}/>
        <label>固定候选<select value={candidate} onChange={e => setCandidate(e.target.value)} required>
          <option value="">请选择</option>{currentOptions.candidates.map(item =>
            <option key={item.candidate_id} value={item.candidate_id}>{item.label} · {item.candidate_id}</option>)}
        </select></label>
        {!currentOptions.candidates.length && <p className="muted">没有满足当前条件的候选。</p>}
        {currentOptions.management_start_url
          ? <p className="muted">管理端资源查询地址（不授予访问权）：<code>{currentOptions.management_start_url}</code></p>
          : <p className="muted">管理端资源查询地址尚未配置。</p>}
      </>}
      <button className="primary" disabled={!canStart || optionsLoading || !!optionsError || !selected}>申请开启</button>
    </form>}
    {current?.map((session, index) => <HumanTestRound key={session.session_id} hub={hub} task={task} session={session}
      latest={index === 0} fresh={freshSessions}/>)}
  </section>;
}
