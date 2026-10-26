import { useMemo, useRef, useState } from "react";
import type {
  DemoController, DemoModal, DemoPlan, DemoTask, ModalKind, NewTaskInput, TaskFilter,
} from "./contracts";

const initialTasks: DemoTask[] = [
  {
    id: "TASK-1042", title: "验证构建与交付",
    goal: "验证便签服务的构建与交付，保留每一步可复核的事实。",
    budget: 12, status: "waiting", updatedAt: "10:42",
  },
  {
    id: "TASK-1041", title: "整理需求引用",
    goal: "整理固定来源与需求修订，保持任务范围和引用一致。",
    budget: 8.5, status: "ready", updatedAt: "10:36",
  },
  {
    id: "TASK-1039", title: "补充验收说明",
    goal: "补充便签服务的验收说明，分别记录验证事实与待确认事项。",
    budget: 6, status: "ready", updatedAt: "10:28",
  },
];

const initialPlan: DemoPlan = {
  id: "PLAN-082",
  digest: "sha256:e7cf429d83b9dd9f5cd8b1a7473bf02c94f5c257f5ff55eceab80cc2249c4d0b",
  currentRelease: "0.7.0", release: "0.7.1", configFrom: 3, configTo: 4,
  target: "s2413（演示）", environment: "交付验证",
  expiresAt: "2026-10-26 11:00 CST", approved: true,
};

function clockTime() {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(new Date());
}

export function useDemo(): DemoController {
  const [tasks, setTasks] = useState<DemoTask[]>(initialTasks);
  const [selectedId, setSelectedId] = useState("TASK-1042");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [connected, setConnected] = useState(true);
  const [lastSync, setLastSync] = useState("10:42 CST");
  const [plan, setPlan] = useState<DemoPlan>(initialPlan);
  const [checkedAt, setCheckedAt] = useState("10:40");
  const [approvedAt, setApprovedAt] = useState("10:41");
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const [modal, setModal] = useState<DemoModal>(null);
  const nextTaskId = useRef(1043);
  const selectedTask = tasks.find((task) => task.id === selectedId) ?? initialTasks[0]!;
  const visibleTasks = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return tasks.filter((task) => {
      const matchesQuery = `${task.id} ${task.title} ${task.goal}`.toLocaleLowerCase().includes(needle);
      const matchesFilter = filter === "all" || (filter === "ready"
        ? task.status === "ready" : task.status !== "ready");
      return matchesQuery && matchesFilter;
    });
  }, [tasks, query, filter]);

  function requireConnection(action: string) {
    if (connected) return true;
    setNotice(`当前离线，无法${action}。可继续阅读已有快照，或在连接设置中恢复连接。`);
    return false;
  }

  function selectTask(id: string) {
    if (tasks.some((task) => task.id === id)) setSelectedId(id);
  }

  function openModal(kind: ModalKind, reference?: string) {
    setNotice("");
    setModal({ kind, reference });
  }

  function toggleConnection() {
    setConnected(!connected);
    if (connected) {
      setNotice("已切换为离线。保留任务、计划及 Op-218 的原身份，写操作暂不可用。");
    } else {
      setLastSync(`${clockTime()} CST`);
      setNotice("连接已恢复。沿用原任务与 Op-218；归档传输仍为 unknown，后续步骤未启动。");
    }
  }

  function createTask(input: NewTaskInput) {
    if (!requireConnection("创建任务")) return false;
    const title = input.title.trim();
    const goal = input.goal.trim();
    if (!title || !goal || !Number.isFinite(input.budget) || input.budget <= 0) {
      setNotice("请填写任务名称、目标和大于 0 的预算。");
      return false;
    }
    const task: DemoTask = {
      id: `TASK-${nextTaskId.current++}`, title, goal, budget: input.budget,
      status: "ready", updatedAt: clockTime(),
    };
    setTasks((current) => [task, ...current]);
    setSelectedId(task.id);
    setQuery("");
    setFilter("all");
    setModal(null);
    setNotice(`${task.id} 已创建，状态为待启动。`);
    return true;
  }

  function startTask() {
    if (!requireConnection("启动任务")) return;
    if (selectedTask.status !== "ready") {
      setNotice(selectedTask.status === "cancel_requested"
        ? "此任务已请求取消，停止仍待确认，不能重新启动。"
        : "启动请求已接收，任务仍在等待事实，不重复启动。");
      return;
    }
    setTasks((current) => current.map((task) => task.id === selectedId
      ? { ...task, status: "waiting", updatedAt: clockTime() } : task));
    setNotice(`${selectedTask.id} 启动请求已接收。当前为等待中，尚未产生完成结论。`);
  }

  function cancelTask(reason: string) {
    if (!requireConnection("请求取消")) return false;
    const cancelReason = reason.trim();
    if (!cancelReason) {
      setNotice("请填写取消原因，以保留可复核的控制记录。");
      return false;
    }
    if (selectedTask.status === "cancel_requested") {
      setNotice("取消请求已记录。停止仍待确认，冲突资源与磁盘占用继续保留。");
      return false;
    }
    setTasks((current) => current.map((task) => task.id === selectedId
      ? { ...task, status: "cancel_requested", cancelReason, updatedAt: clockTime() } : task));
    setModal(null);
    setNotice(`${selectedTask.id} 已请求取消。物理停止待确认，原操作身份与资源占用保留。`);
    return true;
  }

  function checkPlan() {
    if (!requireConnection("核对计划")) return;
    setCheckedAt(clockTime());
    setNotice("已核对本地计划快照中的固定输入。原批准仍保留；Op-218 归档传输仍为 unknown，后续步骤未启动。");
  }

  function approvePlan() {
    if (!requireConnection("批准计划")) return;
    if (plan.approved) {
      setNotice(`${plan.id} 已于 ${approvedAt} CST 批准，不重复产生批准记录。`);
      return;
    }
    if (!approvalConfirmed) {
      setNotice("请先确认已核对目标、配置与完整计划摘要。");
      return;
    }
    setPlan((current) => ({ ...current, approved: true }));
    setApprovedAt(clockTime());
    setNotice(`${plan.id} 的批准已记录。执行尚未开始，批准不代表交付完成。`);
  }

  function refresh() {
    if (!requireConnection("刷新快照")) return;
    setLastSync(`${clockTime()} CST`);
    setNotice("已按原身份查询本地快照：Op-218 归档传输仍为 unknown，后续步骤未启动，未重放操作。");
  }

  return {
    tasks, visibleTasks, selectedTask, query, filter, connected, lastSync, plan,
    checkedAt, approvedAt, approvalConfirmed, notice, modal, setQuery, setFilter,
    selectTask, setApprovalConfirmed, openModal, closeModal: () => setModal(null),
    dismissNotice: () => setNotice(""), toggleConnection, createTask, startTask,
    cancelTask, checkPlan, approvePlan, refresh,
  };
}
