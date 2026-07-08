import { formatDateTime, formatJson } from '../../shared/api/formatters'
import type { AgentRun, EventLog } from '../../shared/types/api'

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
  error: '已降级为轮询/重连边界',
}

/**
 * Agent Timeline 与 Event Log。
 *
 * AgentRun 来自 M2 内部联调记录，Event Log 来自 `event_logs`；M3 不把
 * 这些记录渲染成“自动 Agent 已执行”的结论。
 */
export function TaskTimeline({ agentRuns, events, streamStatus }: TaskTimelineProps) {
  return (
    <section className="sub-panel" aria-labelledby="timeline-title">
      <div className="inline-heading">
        <h3 id="timeline-title">Agent Timeline / Event Log</h3>
        <span className="stream-chip">SSE：{streamStatusLabel[streamStatus]}</span>
      </div>
      <p className="muted">M2 SSE 只回放当前事件并追加 heartbeat；界面会在事件或刷新时重新读取 Timeline。</p>

      <div className="split-grid">
        <div>
          <h4>Agent Runs</h4>
          {agentRuns.length === 0 ? <p className="empty-state">暂无真实 AgentRun 记录。</p> : null}
          {agentRuns.map((run) => (
            <article className="record-card" key={run.id}>
              <strong>{run.agent_type}</strong>
              <span>{run.status}</span>
              <small>
                {formatDateTime(run.started_at)} - {formatDateTime(run.finished_at)}
              </small>
              <small>
                tokens: {run.input_tokens}/{run.output_tokens} · cost: {run.cost_usd}
              </small>
            </article>
          ))}
        </div>

        <div>
          <h4>Event Log</h4>
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
        </div>
      </div>
    </section>
  )
}
