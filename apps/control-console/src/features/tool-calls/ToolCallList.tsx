import { formatDateTime, formatJson } from '../../shared/api/formatters'
import type { ToolCall } from '../../shared/types/api'

interface ToolCallListProps {
  toolCalls: ToolCall[]
}

/**
 * Tool Call 列表。
 *
 * 响应只展示后端提供的 `arguments_summary`，避免前端绕过权限读取完整
 * 参数。真实 Tool Gateway 执行会在 M5 接入。
 */
export function ToolCallList({ toolCalls }: ToolCallListProps) {
  return (
    <section className="sub-panel" aria-labelledby="tool-call-title">
      <h3 id="tool-call-title">Tool Calls</h3>
      {toolCalls.length === 0 ? <p className="empty-state">暂无真实 ToolCall 记录。</p> : null}
      <div className="record-list">
        {toolCalls.map((toolCall) => (
          <article className="record-card" key={toolCall.id}>
            <div className="card-toolbar">
              <strong>{toolCall.tool_name}</strong>
              <span className="risk-chip">{toolCall.risk_level}</span>
            </div>
            <dl className="meta-grid">
              <div>
                <dt>状态</dt>
                <dd>{toolCall.status}</dd>
              </div>
              <div>
                <dt>参数摘要</dt>
                <dd>{toolCall.arguments_summary}</dd>
              </div>
              <div>
                <dt>审批 ID</dt>
                <dd>{toolCall.approval_id ?? '无'}</dd>
              </div>
              <div>
                <dt>时间</dt>
                <dd>
                  {formatDateTime(toolCall.started_at)} - {formatDateTime(toolCall.finished_at)}
                </dd>
              </div>
            </dl>
            <pre>{formatJson(toolCall.result_json)}</pre>
          </article>
        ))}
      </div>
    </section>
  )
}
