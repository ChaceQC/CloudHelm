import { formatDateTime, formatJson } from '../../shared/api/formatters'
import type { AgentRun, EventLog } from '../../shared/types/api'
import { AgentRunCard } from './AgentRunCard'
import { orderAgentRunsForTimeline } from './taskTimelineOrdering'

interface TaskTimelineProps {
  agentRuns: AgentRun[]
  events: EventLog[]
  streamStatus: 'idle' | 'connecting' | 'open' | 'closed' | 'error'
}

const streamStatusLabel: Record<TaskTimelineProps['streamStatus'], string> = {
  idle: '未连接',
  connecting: '连接中',
  open: '已连接',
  closed: '已关闭',
  error: '连接异常，等待重连',
}

/**
 * Agent Timeline 与 Event Log。
 *
 * AgentRun 来自当前任务各阶段的真实 Agent 执行记录，Event Log 来自
 * `event_logs`；失败运行也按真实开始时间保留在审计顺序中。
 */
export function TaskTimeline({ agentRuns, events, streamStatus }: TaskTimelineProps) {
  const orderedAgentRuns = orderAgentRunsForTimeline(agentRuns)

  return (
    <section className="sub-panel timeline-panel" aria-labelledby="timeline-title">
      <div className="inline-heading">
        <div>
          <p className="eyebrow">运行证据</p>
          <h3 id="timeline-title">Agent Timeline</h3>
        </div>
        <span className="stream-chip">SSE：{streamStatusLabel[streamStatus]}</span>
      </div>
      <p className="muted">每个角色仍属于同一 Task 主会话；缓存数字来自供应商 usage，格式修复重试会逐请求展开。</p>

      <div className="timeline-layout">
        <div className="agent-run-list">
          {orderedAgentRuns.length === 0 ? <p className="empty-state">暂无真实 AgentRun 记录。</p> : null}
          {orderedAgentRuns.map((run) => <AgentRunCard key={run.id} run={run} />)}
        </div>

        <aside className="event-log-panel" aria-label="任务事件日志">
          <div className="event-log-heading">
            <div>
              <p className="eyebrow">审计轨迹</p>
              <h4>Event Log</h4>
            </div>
            <span>{events.length}</span>
          </div>
          {events.length === 0 ? <p className="empty-state">暂无真实事件。</p> : null}
          {events.map((event) => (
            <article className="record-card event-record" key={event.id}>
              <strong>{event.event_type}</strong>
              <small>
                {event.actor_type}
                {event.actor_id === null ? '' : ` / ${event.actor_id}`} · {formatDateTime(event.created_at)}
              </small>
              <pre>{formatJson(event.payload)}</pre>
            </article>
          ))}
        </aside>
      </div>
    </section>
  )
}
