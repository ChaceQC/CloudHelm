import type { RiskLevel, TaskStatus } from '../../shared/types/api'

const statusLabel: Record<TaskStatus, string> = {
  created: '已创建',
  running: '运行中',
  waiting_approval: '待审批',
  paused: '已暂停',
  failed: '失败',
  done: '完成',
  cancelled: '已取消',
}

/**
 * 任务状态与风险等级展示组件。
 *
 * 文案来自后端枚举的稳定映射；颜色只表达状态，不改变业务含义。
 */
export function TaskStatusBadge({ status, riskLevel }: { status: TaskStatus; riskLevel?: RiskLevel }) {
  return (
    <span className={`status-badge status-${status}`}>
      {statusLabel[status]}
      {riskLevel !== undefined ? <span className="risk-chip">{riskLevel}</span> : null}
    </span>
  )
}
