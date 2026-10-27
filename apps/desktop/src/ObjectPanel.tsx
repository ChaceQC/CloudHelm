import { useEffect, useState } from "react";
import { codeOf, objectPath, sessionChanged } from "./api";
import type { Hub } from "./useHub";
import type { DeliveryObject } from "./types";
import { Empty, Facts, JsonView } from "./ui";

const routes = { release: "releases", configuration: "environment-configurations", environment: "environments", plan: "deployment-plans" };
export const kindNames = { release: "Release", configuration: "配置修订", environment: "环境", plan: "部署计划" };

export function ObjectPanel({ hub, object }: { hub: Hub; object?: DeliveryObject }) {
  const [detail, setDetail] = useState<unknown>(null);
  const [error, setError] = useState("");
  const project = hub.snapshot?.project.project_id;
  useEffect(() => {
    let active = true; setDetail(null); setError("");
    if (!object || !project) return;
    void hub.query(objectPath(project, routes[object.kind], object.object_id)).then(value => {
      if (active) setDetail(value);
    }).catch(reason => { if (active && !sessionChanged(reason)) setError(codeOf(reason)); });
    return () => { active = false; };
  }, [project, object?.object_id, hub.snapshot?.captured_at]);
  if (!object) return <Empty>选择交付对象</Empty>;
  return <article className="detail"><h2>{kindNames[object.kind]}</h2><Facts values={{ "对象": object.object_id,
    "修订": object.revision, "目标": object.target_id, "Release": object.release_id,
    "配置": object.config_revision_id, "原 Operation": object.operation_id, "摘要": object.digest }}/>
    {error ? <p className="error">{error}</p> : detail ? <JsonView value={detail} title="服务端当前事实"/> : <p className="muted">正在查询…</p>}
  </article>;
}
