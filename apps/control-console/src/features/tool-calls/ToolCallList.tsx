import { formatDateTime, formatJson } from '../../shared/api/formatters'
import type { ToolCall } from '../../shared/types/api'

interface ToolCallListProps {
  toolCalls: ToolCall[]
}

/**
 * Tool Call 列表。
 *
 * 响应只展示后端提供的 `arguments_summary`、输出摘要和错误码，避免前端
 * 绕过权限读取完整参数或完整命令输出。布局保持 Codex 式低饱和面板。
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
                <dt>幂等键</dt>
                <dd>{toolCall.idempotency_key ?? '未记录'}</dd>
              </div>
              <div>
                <dt>耗时</dt>
                <dd>{toolCall.duration_ms === null ? '未完成' : `${toolCall.duration_ms} ms`}</dd>
              </div>
              <div>
                <dt>错误码</dt>
                <dd>{toolCall.error_code ?? '无'}</dd>
              </div>
              <div>
                <dt>时间</dt>
                <dd>
                  {formatDateTime(toolCall.started_at)} - {formatDateTime(toolCall.finished_at)}
                </dd>
              </div>
            </dl>
            {toolCall.result_summary === null ? null : <p className="tool-summary">{toolCall.result_summary}</p>}
            <div className="tool-output-grid">
              <div>
                <h4>stdout</h4>
                <pre>{toolCall.stdout_summary ?? '无 stdout 摘要。'}</pre>
              </div>
              <div>
                <h4>stderr</h4>
                <pre>{toolCall.stderr_summary ?? '无 stderr 摘要。'}</pre>
              </div>
            </div>
            <h4>审计摘要</h4>
            <pre>{formatJson(toolCall.audit_json)}</pre>
            <h4>结果 JSON</h4>
            <pre>{formatJson(toolCall.result_json)}</pre>
          </article>
        ))}
      </div>
    </section>
  )
}
