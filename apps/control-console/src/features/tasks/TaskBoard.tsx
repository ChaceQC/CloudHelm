import { useState } from 'react'
import { formatApiError } from '../../shared/api/formatters'
import type { DecisionRequest, Task, TaskCreateInput, TaskStatus } from '../../shared/types/api'
import { TaskCreateForm } from './TaskCreateForm'
import { TaskStatusBadge } from './TaskStatusBadge'

interface TaskBoardProps {
  projectSelected: boolean
  tasks: Task[]
  status: 'idle' | 'loading' | 'ready' | 'error'
  error: string | null
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onCreateTask: (payload: Omit<TaskCreateInput, 'project_id'>) => Promise<Task>
  onTaskCreated: (task: Task) => void
  onRunTaskAction: (taskId: string, action: 'pause' | 'resume' | 'cancel', payload: DecisionRequest) => Promise<Task>
  onRefresh: () => void
}

const boardStatuses: TaskStatus[] = [
  'created',
  'running',
  'waiting_approval',
  'paused',
  'failed',
  'done',
  'cancelled',
]

const boardStatusTitle: Record<TaskStatus, string> = {
  created: 'Created',
  running: 'Running',
  waiting_approval: 'Waiting Approval',
  paused: 'Paused',
  failed: 'Failed',
  done: 'Done',
  cancelled: 'Cancelled',
}

/**
 * Task Board 与需求输入区。
 *
 * 看板按后端返回的 `status` 分组，不创建任何前端本地假任务。任务操作
 * 使用真实 pause/resume/cancel API，并把失败原因展示给用户。
 */
export function TaskBoard({
  projectSelected,
  tasks,
  status,
  error,
  selectedTaskId,
  onSelectTask,
  onCreateTask,
  onTaskCreated,
  onRunTaskAction,
  onRefresh,
}: TaskBoardProps) {
  const [actionError, setActionError] = useState<string | null>(null)

  const runAction = async (taskId: string, action: 'pause' | 'resume' | 'cancel') => {
    setActionError(null)
    try {
      await onRunTaskAction(taskId, action, {
        actor_id: 'control-console',
        reason: `用户在控制台执行 ${action}`,
      })
    } catch (runError) {
      setActionError(formatApiError(runError))
    }
  }

  return (
    <section className="panel task-board" aria-labelledby="task-board-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Task Board</p>
          <h2 id="task-board-title">任务主流程</h2>
        </div>
        <button type="button" className="ghost-button" onClick={onRefresh} disabled={!projectSelected}>
          刷新任务
        </button>
      </div>

      <TaskCreateForm disabled={!projectSelected} onCreate={onCreateTask} onCreated={onTaskCreated} />

      {status === 'idle' ? <p className="empty-state">请先在左侧选择或创建项目。</p> : null}
      {status === 'loading' ? <p className="status-line">正在加载真实任务列表...</p> : null}
      {status === 'error' ? (
        <div className="status-error" role="alert">
          <strong>任务加载失败</strong>
          <p>{error}</p>
        </div>
      ) : null}
      {actionError !== null ? <p className="form-error">{actionError}</p> : null}

      <div className="board-grid">
        {boardStatuses.map((boardStatus) => {
          const columnTasks = tasks.filter((task) => task.status === boardStatus)
          return (
            <div className="board-column" key={boardStatus}>
              <h3>{boardStatusTitle[boardStatus]}</h3>
              {columnTasks.length === 0 ? <p className="muted">无真实任务</p> : null}
              {columnTasks.map((task) => (
                <article
                  key={task.id}
                  className={`task-card${task.id === selectedTaskId ? ' selected' : ''}`}
                  onClick={() => onSelectTask(task.id)}
                >
                  <div className="task-card-topline">
                    <TaskStatusBadge status={task.status} riskLevel={task.risk_level} />
                    <small>{task.current_phase}</small>
                  </div>
                  <h4>{task.title}</h4>
                  <p>{task.description}</p>
                  <div className="task-actions" onClick={(event) => event.stopPropagation()}>
                    <button type="button" className="tiny-button" onClick={() => void runAction(task.id, 'pause')}>
                      Pause
                    </button>
                    <button type="button" className="tiny-button" onClick={() => void runAction(task.id, 'resume')}>
                      Resume
                    </button>
                    <button type="button" className="tiny-button danger" onClick={() => void runAction(task.id, 'cancel')}>
                      Cancel
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )
        })}
      </div>
    </section>
  )
}
