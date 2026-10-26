import { useCallback, useMemo, useRef, useState } from "react";
import type { DemoController, DemoModal, DemoPlan, DemoTask, ModalKind, NewTaskInput, TaskFilter } from "./contracts";

const INITIAL_TASKS: DemoTask[] = [
  {
    id: "TASK-1042", title: "验证构建与交付", budget: 12, status: "waiting", updatedAt: "10:42",
    goal: "核对构建候选、配置修订与 s2413 演示目标的交付输入，等待 Op-218 原操作结果。",
  },
  {
    id: "TASK-1041", title: "整理需求引用", budget: 8.5, status: "ready", updatedAt: "10:20",
    goal: "整理 SRC-021 与 REQ-014 r3 的关联，保留来源与版本。",
  },
  {
    id: "TASK-1039", title: "补充验收说明", budget: 6, status: "ready", updatedAt: "09:58",
    goal: "补充 ACC-014 r2 的验收条目、预期结果与证据索引。",
  },
];

const INITIAL_PLAN: DemoPlan = {
  id: "PLAN-082",
  digest: "7a2f0b19c3d4e5f60817293a4b5c6d7e8f9012a3b4c5d6e7f8091a2b3c4d5e6f",
  currentRelease: "0.7.0", release: "0.7.1", configFrom: 3, configTo: 4,
  target: "s2413（演示）", environment: "环境交付验证",
  expiresAt: "2026-10-26 11:00 CST", approved: true,
};

function currentTime() {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date());
}

export function useDemo(): DemoController {
  const [tasks, setTasks] = useState<DemoTask[]>(INITIAL_TASKS);
  const [selectedId, setSelectedId] = useState("TASK-1042");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [connected, setConnected] = useState(true);
  const [lastSync, setLastSync] = useState("10:42 CST");
  const [plan, setPlan] = useState<DemoPlan>(INITIAL_PLAN);
  const [checkedAt, setCheckedAt] = useState("10:40");
  const [approvedAt, setApprovedAt] = useState("10:41");
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const [modal, setModal] = useState<DemoModal>(null);
  const nextTask = useRef(1043);
  const selectedTask = tasks.find((task) => task.id === selectedId) ?? INITIAL_TASKS[0]!;
  const visibleTasks = useMemo(() => {
    const search = query.trim().toLocaleLowerCase();
    return tasks.filter((task) => {
      const matchesFilter = filter === "all" || (filter === "ready" ? task.status === "ready" : task.status !== "ready");
      return matchesFilter && `${task.id} ${task.title} ${task.goal}`.toLocaleLowerCase().includes(search);
    });
  }, [tasks, query, filter]);

  const selectTask = useCallback((id: string) => {
    if (tasks.some((task) => task.id === id)) setSelectedId(id);
  }, [tasks]);

  const openModal = useCallback((kind: ModalKind, reference?: string) => {
    if ((kind === "task" || kind === "cancel") && tasks.some((task) => task.id === reference)) {
      setSelectedId(reference!);
    }
    setModal({ kind, reference });
  }, [tasks]);
  const closeModal = useCallback(() => setModal(null), []);
  const dismissNotice = useCallback(() => setNotice(""), []);

  const requireConnection = useCallback(() => {
    if (connected) return true;
    setNotice("当前离线，写操作不可用。请恢复连接状态后重试，原有业务对象身份保持不变。");
    return false;
  }, [connected]);

  const toggleConnection = useCallback(() => {
    setConnected(!connected);
    setApprovalConfirmed(false);
    setNotice(connected
      ? "已切换为离线快照，写操作已停用；原有业务对象身份保留，摘要需重新确认。"
      : "已恢复本地连接状态，原有业务对象身份保留；请重新核对并确认摘要。");
  }, [connected]);

  const createTask = useCallback((input: NewTaskInput) => {
    if (!requireConnection()) return false;
    const title = input.title.trim();
    const goal = input.goal.trim();
    if (!title || !goal || !Number.isFinite(input.budget) || input.budget <= 0) {
      setNotice("请填写任务名称、目标，并设置大于 0 的预算。");
      return false;
    }
    const task: DemoTask = {
      id: `TASK-${nextTask.current++}`, title, goal, budget: input.budget,
      status: "ready", updatedAt: currentTime(),
    };
    setTasks((current) => [task, ...current]);
    setSelectedId(task.id);
    setQuery("");
    setFilter("all");
    setModal(null);
    setNotice(`${task.id} 已创建，可以检查任务详情后启动。`);
    return true;
  }, [requireConnection]);

  const startTask = useCallback(() => {
    if (!requireConnection()) return;
    if (selectedTask.status !== "ready") {
      setNotice(selectedTask.status === "cancel_requested"
        ? "原取消请求仍待物理停止确认，资源继续保留，不能再次启动。"
        : "原启动请求已接收，请继续查询原任务；尚不表示执行完成。");
      return;
    }
    setTasks((current) => current.map((task) => task.id === selectedTask.id
      ? { ...task, status: "waiting", updatedAt: currentTime() } : task));
    setNotice(`${selectedTask.id} 启动请求已接收，进入等待；接收不等于执行完成。`);
  }, [requireConnection, selectedTask]);

  const cancelTask = useCallback((reason: string) => {
    if (!requireConnection()) return false;
    if (!reason.trim()) {
      setNotice("请填写取消原因，再提交取消请求。");
      return false;
    }
    if (selectedTask.status !== "cancel_requested") {
      setTasks((current) => current.map((task) => task.id === selectedTask.id
        ? { ...task, status: "cancel_requested", cancelReason: reason.trim(), updatedAt: currentTime() } : task));
    }
    setModal(null);
    setNotice(`${selectedTask.id} 取消请求已接收；物理停止待确认，冲突资源继续保留。`);
    return true;
  }, [requireConnection, selectedTask]);

  const checkPlan = useCallback(() => {
    if (!requireConnection()) return;
    setCheckedAt(currentTime());
    setNotice("已刷新 PLAN-082 的本地核对记录；Op-218 仍为 unknown，后续步骤尚未启动。");
  }, [requireConnection]);

  const approvePlan = useCallback(() => {
    if (!requireConnection()) return;
    if (!approvalConfirmed) {
      setNotice("请先确认已核对计划摘要、目标和配置修订。");
      return;
    }
    if (!plan.approved) {
      setPlan((current) => ({ ...current, approved: true }));
      setApprovedAt(currentTime());
    }
    setNotice("PLAN-082 已获批准；批准不表示后续步骤已执行或部署完成。");
  }, [requireConnection, approvalConfirmed, plan.approved]);

  const refresh = useCallback(() => {
    const taskSnapshot = selectedTask.id === "TASK-1042"
      ? "TASK-1042 的原 Op-218 仍为 unknown，没有重放操作或启动后续步骤。"
      : selectedTask.status === "waiting"
        ? `${selectedTask.id} 的启动请求已接收，仍在等待执行结果；接收不等于完成。`
        : selectedTask.status === "cancel_requested"
          ? `${selectedTask.id} 的取消请求已接收，物理停止待确认，冲突资源继续保留。`
          : `${selectedTask.id} 当前可启动，尚未提交启动请求。`;
    if (!connected) {
      setNotice(`当前离线，继续显示 ${lastSync} 的快照；${taskSnapshot}`);
      return;
    }
    setLastSync(`${currentTime()} CST`);
    setNotice(`本地快照已刷新；${taskSnapshot}`);
  }, [connected, lastSync, selectedTask]);

  return {
    tasks, visibleTasks, selectedTask, query, filter, connected, lastSync, plan,
    checkedAt, approvedAt, approvalConfirmed, notice, modal,
    setQuery, setFilter, selectTask, setApprovalConfirmed, openModal, closeModal,
    dismissNotice, toggleConnection, createTask, startTask, cancelTask,
    checkPlan, approvePlan, refresh,
  };
}
