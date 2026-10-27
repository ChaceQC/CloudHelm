import { useEffect, useState } from "react";
import { codeOf, objectPath } from "./api";
import type { Hub } from "./useHub";
import type { Deployment, Json } from "./types";
import { Empty, Facts, JsonView, Status } from "./ui";

export function PlanPanel({ hub, planId }: { hub: Hub; planId: string }) {
  const [value, setValue] = useState<Deployment | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [expires, setExpires] = useState("");
  const projectId = hub.snapshot?.project.project_id ?? "";
  const cursor = hub.snapshot?.cursor;
  const captured = hub.snapshot?.captured_at;
  useEffect(() => {
    let active = true;
    setValue(null); setConfirmed(false); setError("");
    if (!planId || !projectId) return;
    void hub.query<Deployment>(objectPath(projectId, "deployment-plans", planId)).then(next => {
      if (!active) return;
      setValue(next);
      const deadline = Date.parse(String(next.plan.value.start_before));
      setExpires(new Date(Math.min(deadline, Date.now() + 15 * 60000)).toISOString());
    }).catch(reason => { if (active) setError(codeOf(reason)); });
    return () => { active = false; };
  }, [planId, projectId, cursor, captured]);
  if (!planId) return <Empty>选择部署计划</Empty>;
  if (error) return <div className="error">{error}</div>;
  if (!value) return <Empty>正在读取固定计划…</Empty>;
  const plan = value.plan.value;
  const binding = plan.binding as Json;
  const configuration = plan.configuration as Json;
  const config = configuration.configuration as Json;
  const expiry = Date.parse(expires);
  const validTime = Number.isFinite(expiry) && expiry > Date.now() && expiry <= Date.parse(String(plan.start_before));
  return <article className="detail">
    <div className="section-title"><h2>部署计划</h2><Status value={value.status}/></div>
    <Facts values={{ "计划": value.plan.object_id, "目标": binding.target_id, "环境": binding.environment_id,
      "Release": plan.release_id, "起始环境版本": (plan.expected_state as Json).environment_revision,
      "当前环境版本": value.environment_revision,
      "配置修订": config.config_revision_id, "执行截止": plan.start_before,
      "原 Operation": value.operation_id, "失败处理": plan.compensation }}/>
    <div className="digest"><span>固定计划摘要</span><code>{value.plan.digest}</code></div>
    <JsonView value={plan.expected_state} title="起始环境与数据库版本"/>
    <JsonView value={plan.normalized_spec} title="目标服务、配置和资源"/>
    <JsonView value={plan.steps} title="执行步骤与影响"/>
    <JsonView value={plan.step_inputs} title="步骤输入与前后置条件"/>
    {!value.approval ? <form className="approval" onSubmit={e => {
      e.preventDefault();
      if (confirmed && validTime) hub.command(`${objectPath(projectId, "deployment-plans", value.plan.object_id)}/approvals`, {
        plan_digest: value.plan.digest, expires_at: new Date(expires).toISOString(),
      });
    }}><label>批准有效期（带时区）<input value={expires} onChange={e => setExpires(e.target.value)} required/></label>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>
        我已核对本计划摘要、目标、配置、数据库影响与停止核对策略</label>
      <button className="primary" disabled={!hub.can("deployment.approve") || !confirmed || !validTime}>批准此计划</button>
    </form> : <div className="notice">计划已批准；当前执行状态以上方业务事实为准。<JsonView value={value.approval} title="批准记录"/></div>}
    <JsonView value={value} title="完整计划与执行事实"/>
  </article>;
}
