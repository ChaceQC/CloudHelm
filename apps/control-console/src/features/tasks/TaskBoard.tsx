import { useState } from 'react'
import { formatApiError } from '../../shared/api/formatters'
import type { DecisionRequest, Task, TaskCreateInput, TaskStatus } from '../../shared/types/api'
import { TaskCreateForm } from './TaskCreateForm'
import { TaskStatusBadge } from './TaskStatusBadge'
import { canCancelTask, canPauseTask, canResumeTask } from './taskActionPolicy'

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
  created: '已创建',
  running: '进行中',
  waiting_approval: '待审批',
  paused: '已暂停',
  failed: '失败',
  done: '已完成',
  cancelled: '已取消',
}

/**
 * 紧凑任务列表与需求输入区。
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
          <p className="eyebrow">任务导航</p>
          <h2 id="task-board-title">最近任务</h2>
        </div>
        <button
          type="button"
          className="icon-button"
          onClick={onRefresh}
          disabled={!projectSelected}
          aria-label="刷新任务列表"
        >
          ↻
        </button>
      </div>

      <details className="create-disclosure task-create-disclosure">
        <summary><span aria-hidden="true">＋</span> 新建任务</summary>
        <TaskCreateForm disabled={!projectSelected} onCreate={onCreateTask} onCreated={onTaskCreated} />
      </details>

      {status === 'idle' ? <p className="empty-state">请先在左侧选择或创建项目。</p> : null}
      {status === 'loading' ? <p className="status-line">正在加载真实任务列表...</p> : null}
      {status === 'error' ? (
        <div className="status-error" role="alert">
          <strong>任务加载失败</strong>
          <p>{error}</p>
        </div>
      ) : null}
      {actionError !== null ? <p className="form-error">{actionError}</p> : null}

      {status === 'ready' && tasks.length === 0 ? <p className="empty-state">当前项目暂无任务。</p> : null}

      <div className="task-list">
        {boardStatuses.map((boardStatus) => {
          const columnTasks = tasks.filter((task) => task.status === boardStatus)
          if (columnTasks.length === 0) {
            return null
          }

          return (
            <section className="task-group" key={boardStatus} aria-label={boardStatusTitle[boardStatus]}>
              <div className="task-group-heading">
                <h3>{boardStatusTitle[boardStatus]}</h3>
                <span>{columnTasks.length}</span>
              </div>
              {columnTasks.map((task) => (
                <article key={task.id} className={`task-card${task.id === selectedTaskId ? ' selected' : ''}`}>
                  <button
                    type="button"
                    className="task-select"
                    onClick={() => onSelectTask(task.id)}
                    aria-current={task.id === selectedTaskId ? 'page' : undefined}
                  >
                    <span className="task-card-topline">
                      <TaskStatusBadge status={task.status} riskLevel={task.risk_level} />
                      <small>{task.current_phase}</small>
                    </span>
                    <strong>{task.title}</strong>
                    <span className="task-description">{task.description}</span>
                  </button>
                  <div className="task-actions">
                    <button
                      type="button"
                      className="tiny-button"
                      onClick={() => void runAction(task.id, 'pause')}
                      disabled={!canPauseTask(task.status)}
                    >
                      暂停
                    </button>
                    <button
                      type="button"
                      className="tiny-button"
                      onClick={() => void runAction(task.id, 'resume')}
                      disabled={!canResumeTask(task.status)}
                    >
                      继续
                    </button>
                    <button
                      type="button"
                      className="tiny-button danger"
                      onClick={() => void runAction(task.id, 'cancel')}
                      disabled={!canCancelTask(task.status)}
                    >
                      取消
                    </button>
                  </div>
                </article>
              ))}
            </section>
          )
        })}
      </div>
    </section>
  )
}
