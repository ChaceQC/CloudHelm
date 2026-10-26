import { useMemo, useRef, useState } from "react";
import type { DemoController, DemoModal, DemoPlan, DemoTask, ModalKind, NewTaskInput, TaskFilter } from "./contracts";

const FIRST_TASK: DemoTask = {
  id: "TASK-1042",
  title: "验证构建与交付",
  goal: "核对固定构建输入、交付计划与验收引用；沿原身份查询 Op-218 的实际结果。",
  budget: 12,
  status: "waiting",
  updatedAt: "10:42 CST",
};

const INITIAL_TASKS: DemoTask[] = [
  FIRST_TASK,
  { id: "TASK-1041", title: "整理需求引用", goal: "整理 SRC-021、REQ-014 r3 与 ACC-014 r2 的对应关系，保留来源与修订。", budget: 8.5, status: "ready", updatedAt: "10:35 CST" },
  { id: "TASK-1039", title: "补充验收说明", goal: "补充构建、交付和健康观察的验收说明，分开记录预期与实际结果。", budget: 6, status: "ready", updatedAt: "10:28 CST" },
];

const INITIAL_PLAN: DemoPlan = {
  id: "PLAN-083",
  digest: "sha256:8c4cce846e1e36c7d4ef10f275307b861176c6e270d2f9c815bd29aaedb34f20",
  currentRelease: "0.7.0",
  release: "0.7.1",
  configFrom: 3,
  configTo: 4,
  target: "s2413（演示）",
  environment: "环境交付验证",
  expiresAt: "2026-10-26 11:00 CST",
  approved: false,
};

export function useDemo(): DemoController {
  const [tasks, setTasks] = useState<DemoTask[]>(INITIAL_TASKS);
  const [selectedId, setSelectedId] = useState(FIRST_TASK.id);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [connected, setConnected] = useState(true);
  const [lastSync, setLastSync] = useState("10:42 CST");
  const [plan, setPlan] = useState<DemoPlan>(INITIAL_PLAN);
  const [checkedAt, setCheckedAt] = useState("10:40 CST");
  const [approvedAt, setApprovedAt] = useState("");
  const [approvalConfirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const [modal, setModal] = useState<DemoModal>(null);
  const nextTask = useRef(1043);
  const demoMinute = useRef(43);
  const selectedTask = tasks.find((task) => task.id === selectedId) ?? FIRST_TASK;
  const visibleTasks = useMemo(() => {
    const search = query.trim().toLocaleLowerCase();
    return tasks.filter((task) => {
      const matchesQuery = `${task.id} ${task.title} ${task.goal}`.toLocaleLowerCase().includes(search);
      const matchesFilter = filter === "all" || (filter === "ready" ? task.status === "ready" : task.status !== "ready");
      return matchesQuery && matchesFilter;
    });
  }, [tasks, query, filter]);

  // Keep this fixed input on its demonstration date and within its approval window.
  function nextTime() {
    const minute = Math.min(demoMinute.current++, 59);
    return `10:${minute.toString().padStart(2, "0")} CST`;
  }

  function offline(action: string) {
    if (connected) return false;
    setNotice(`连接已断开，暂不能${action}。当前显示最近同步快照。`);
    return true;
  }

  function openModal(kind: ModalKind, reference?: string) {
    setModal({ kind, reference });
  }

  function selectTask(id: string) {
    if (tasks.some((task) => task.id === id)) setSelectedId(id);
  }

  function setApprovalConfirmed(value: boolean) {
    if (value && offline("确认审批")) return;
    if (!plan.approved) setConfirmed(value);
  }

  function toggleConnection() {
    setConnected(!connected);
    if (connected) {
      setConfirmed(false);
      setNotice("连接已断开；最近快照仍可查看，写操作已暂停。");
    } else {
      setLastSync(nextTime());
      setNotice("连接已恢复。请核对计划条件与摘要后继续。");
    }
  }

  function createTask(input: NewTaskInput) {
    if (offline("创建任务")) return false;
    const title = input.title.trim();
    const goal = input.goal.trim();
    if (!title || title.length > 80 || !goal || goal.length > 600 || !Number.isFinite(input.budget) || input.budget <= 0) {
      setNotice("请填写任务名称、目标和大于零的有效预算。");
      return false;
    }
    const task: DemoTask = { id: `TASK-${nextTask.current++}`, title, goal, budget: input.budget, status: "ready", updatedAt: nextTime() };
    setTasks((current) => [task, ...current]);
    setSelectedId(task.id);
    setQuery("");
    setFilter("all");
    setNotice(`${task.id} 已创建，尚未启动。`);
    return true;
  }

  function startTask() {
    if (offline("启动任务")) return;
    if (selectedTask.status === "cancel_requested") {
      setNotice("该任务已请求取消，停止尚待确认，暂不能重新启动。");
      return;
    }
    if (selectedTask.status === "waiting") {
      setNotice(selectedTask.id === FIRST_TASK.id ? "Op-218 的结果仍为 unknown，请先查询原操作。" : "该任务已有启动请求，正在等待执行结果。");
      return;
    }
    const updatedAt = nextTime();
    setTasks((current) => current.map((task) => task.id === selectedId ? { ...task, status: "waiting", updatedAt } : task));
    setNotice(`${selectedTask.id} 的启动请求已接收，等待执行；尚无完成结果。`);
  }

  function cancelTask(reason: string) {
    if (offline("请求取消")) return false;
    const cancelReason = reason.trim();
    if (!cancelReason || cancelReason.length > 500) {
      setNotice("请填写取消原因，最多 500 个字。");
      return false;
    }
    if (selectedTask.status === "cancel_requested") {
      setNotice("该任务已请求取消。停止仍待确认，资源继续保留。");
      return true;
    }
    const updatedAt = nextTime();
    setTasks((current) => current.map((task) => task.id === selectedId ? { ...task, status: "cancel_requested", cancelReason, updatedAt } : task));
    setNotice(`${selectedTask.id} 已请求取消。停止待确认，相关资源继续保留。`);
    return true;
  }

  function checkPlan() {
    if (offline("检查计划条件")) return;
    if (plan.approved) {
      setNotice("计划已批准，执行尚未开始，仍需等待执行事实。");
      return;
    }
    const checked = nextTime();
    setCheckedAt(checked);
    setLastSync(checked);
    setConfirmed(false);
    setNotice(`条件检查通过（${checked}）：起始 Release、配置修订与目标一致。请核对完整摘要。`);
  }

  function approvePlan() {
    if (offline("批准计划")) return;
    if (plan.approved) {
      setNotice("该计划已批准，执行尚未开始。");
      return;
    }
    if (!checkedAt) {
      setNotice("请先检查计划条件，再核对摘要并批准。");
      return;
    }
    if (!approvalConfirmed) {
      setNotice("请先勾选确认，核对目标、起始状态、配置修订和完整摘要。");
      return;
    }
    setPlan((current) => ({ ...current, approved: true }));
    setApprovedAt(nextTime());
    setNotice(`${plan.id} 已批准；执行尚未开始，执行结果与健康状态仍待确认。`);
  }

  function refresh() {
    if (offline("刷新快照")) return;
    setLastSync(nextTime());
    const planOperation = modal?.kind === "operation" && modal.reference && modal.reference !== "Op-218";
    setNotice(planOperation ? `${plan.id} 执行尚未开始，暂无可核对的执行结果。` : "快照已更新。Op-218 仍为 unknown，结果待核对，资源继续保留。");
  }

  return {
    tasks, visibleTasks, selectedTask, query, filter, connected, lastSync, plan, checkedAt, approvedAt, approvalConfirmed, notice, modal,
    setQuery, setFilter, selectTask, setApprovalConfirmed, openModal,
    closeModal: () => setModal(null), dismissNotice: () => setNotice(""),
    toggleConnection, createTask, startTask, cancelTask, checkPlan, approvePlan, refresh,
  };
}
