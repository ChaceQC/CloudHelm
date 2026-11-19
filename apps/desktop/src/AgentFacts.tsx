import type { AgentRunDetail, AgentSummary } from "./agent-contract.generated";
import { Facts, Status } from "./ui";

const reference = (ref: AgentRunDetail["input_set_ref"]) => `${ref.kind} · ${ref.object_id} · 修订 ${ref.revision}`;
const gateLabels = { none: "非门槛", start: "启动门槛", completion: "Task 完成门槛" };
const toolLabels = { call: "调用", return: "返回", retry: "重试" };
const unknownAmount = "unknown · 待核对";

export function AgentWorkItemFacts({ item }: { item: AgentSummary["work_items"][number] }) {
  const capabilities = item.capabilities;
  const entries = [
    ["受管源码", capabilities.managed_source], ["参照构建", capabilities.build],
    ["正式预览", capabilities.formal_preview], ["人测", capabilities.human_test],
  ] as const;
  return <details className="json">
    <summary>{item.goal} · {item.state}</summary>
    <Facts values={{ "工作项": item.work_item_id, "工作项修订": item.revision, "必需": item.required ? "是" : "否",
      "所属 Session": item.owner_session_id, "阻塞原因": item.blocked_reason,
      "允许跳过人测": capabilities.human_test_skip_allowed == null ? null : capabilities.human_test_skip_allowed ? "是" : "否" }}/>
    {entries.map(([label, capability]) => <div key={label}>
      <strong>{label} · {capability.available ? "可用" : "不可用"}</strong>
      <Facts values={{ "原因": capability.reason, "适用规则": gateLabels[capability.gate_phase ?? "none"],
        ...(capability.evidence_refs?.length && { "登记证据": capability.evidence_refs.map(reference).join("；") }),
        ...(capability.runner_evidence_ref && { "Runner 能力证据": capability.runner_evidence_ref }),
        ...(capability.policy_ref && { "策略": reference(capability.policy_ref) }) }}/>
    </div>)}
    {!!capabilities.prerequisites.length && <><h5>声明的前置证据</h5>
      {capabilities.prerequisites.map(item => <Facts key={`${reference(item.subject_ref)}:${reference(item.evidence_ref)}`}
        values={{ "依赖": reference(item.subject_ref), "所需证据": reference(item.evidence_ref) }}/>)}</>}
  </details>;
}

export function AgentWaitFacts({ wait }: { wait: AgentSummary["waits"][number] }) {
  return <div><strong>等待条件 · {wait.wait_condition_id}</strong> <Status value={wait.state}/>
    <Facts values={{ "原 Run": wait.from_run_id, "原调用": wait.tool_call_id, "原操作": wait.operation_id,
      "续接 Run": wait.continuation_run_id, "属于完成门槛": wait.required_for_completion ? "是" : "否" }}/>
  </div>;
}

export function AgentRunFacts({ run, currency }: { run: AgentRunDetail; currency: string }) {
  return <div>
    {run.truncated && <p className="notice">Run 详情已截断，仅显示已返回的事实。</p>}
    <Status value={run.state}/>
    <Facts values={{ "工作项": `${run.work_item_id} · r${run.work_item_revision}`,
      "Run 结果": run.outcome, "结果原因": run.reason_code, "输入集": reference(run.input_set_ref),
      "工具协议": run.tool_protocol_revision, "请求次数": run.request_count,
      "预留金额": `${run.reserved_cost} ${currency}`, "创建时间": run.created_at,
      "开始时间": run.started_at, "截止时间": run.deadline_at }}/>
    <h5>工具时间线</h5>
    {!run.tool_timeline.length && <p className="muted">无工具事件。</p>}
    {run.tool_timeline.map((event, index) => <div key={index}>
      <strong>{toolLabels[event.kind]} · {event.tool_name}</strong>
      <Facts values={{ "原调用": event.tool_call_id, "原 Run": event.call_run_id, "原操作": event.operation_id }}/>
      {event.summary && <p>{event.summary}</p>}
    </div>)}
    <h5>模型请求</h5>
    {!run.requests.length && <p className="muted">无模型请求记录。</p>}
    {run.requests.map(request => <div key={request.request_record_id}>
      <strong>{request.request_record_id}</strong> <Status value={request.state}/>
      <Facts values={{ "预留金额": `${request.reserved_cost} ${currency}`,
        "计算费用": request.calculated_cost === null ? unknownAmount : `${request.calculated_cost} ${currency}`,
        "账单金额": request.billed_amount === null ? unknownAmount
          : `${request.billed_amount} ${request.billed_currency ?? "（币种待核对）"}`,
        "观察修订": request.observation_revision, "核对证据": request.reconciliation_evidence_ref }}/>
    </div>)}
    {run.waits.map(wait => <AgentWaitFacts key={wait.wait_condition_id} wait={wait}/>)}
    {(run.operation_ids.length > 0 || run.evidence_refs.length > 0 || run.verification_report_id) && <>
      <h5>操作与证据</h5><Facts values={{
        ...(run.operation_ids.length > 0 && { "已关联操作": run.operation_ids.join("；") }),
        ...(run.evidence_refs.length > 0 && { "登记证据": run.evidence_refs.map(reference).join("；") }),
        ...(run.verification_report_id && { "验证报告": run.verification_report_id }),
      }}/>
    </>}
  </div>;
}
