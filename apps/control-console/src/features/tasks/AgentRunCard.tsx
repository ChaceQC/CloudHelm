import { formatDateTime } from '../../shared/api/formatters'
import type { AgentRun, ProviderRequestUsage } from '../../shared/types/api'

interface AgentRunCardProps {
  run: AgentRun
}

const tokenFormatter = new Intl.NumberFormat('zh-CN', {
  notation: 'compact',
  maximumFractionDigits: 1,
})

function formatTokens(value: number): string {
  return tokenFormatter.format(value)
}

function cacheRatio(cachedTokens: number, inputTokens: number): number {
  if (inputTokens <= 0) {
    return 0
  }
  return Math.min(100, Math.round((cachedTokens / inputTokens) * 100))
}

function shortId(value: string | null): string {
  if (value === null) {
    return '未记录'
  }
  return value.length <= 18 ? value : `${value.slice(0, 10)}…${value.slice(-6)}`
}

function RequestUsageRow({
  request,
  index,
}: {
  request: ProviderRequestUsage
  index: number
}) {
  const ratio = cacheRatio(request.cached_input_tokens, request.input_tokens)

  return (
    <li className="provider-request-row">
      <div className="provider-request-heading">
        <span>请求 {index + 1}</span>
        <span className={`cache-status${request.cache_hit ? ' hit' : ''}`}>
          {request.cache_hit ? `缓存命中 ${ratio}%` : '未命中缓存'}
        </span>
      </div>
      <div className="provider-request-metrics">
        <span>输入 {formatTokens(request.input_tokens)}</span>
        <span>缓存 {formatTokens(request.cached_input_tokens)}</span>
        <span>输出 {formatTokens(request.output_tokens)}</span>
      </div>
      <small title={request.response_id ?? undefined}>Response · {shortId(request.response_id)}</small>
    </li>
  )
}

/**
 * 单次 AgentRun 的真实模型调用与缓存证据。
 *
 * 总量和逐请求 usage 均来自 Platform API；缓存状态只由供应商返回的
 * `cached_input_tokens` 推导，前端不估算或模拟命中。
 */
export function AgentRunCard({ run }: AgentRunCardProps) {
  const ratio = cacheRatio(run.cached_input_tokens, run.input_tokens)

  return (
    <article className="agent-run-card">
      <header className="agent-run-header">
        <div>
          <span className="agent-avatar" aria-hidden="true">
            {run.agent_type.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <strong>{run.agent_type}</strong>
            <small>
              Turn {run.conversation_turn ?? '—'} · {run.model_name ?? 'local provider'}
            </small>
          </div>
        </div>
        <span className={`review-status status-${run.status}`}>{run.status}</span>
      </header>

      <div className="agent-usage-strip">
        <div>
          <span>输入</span>
          <strong>{formatTokens(run.input_tokens)}</strong>
        </div>
        <div className="cache-usage">
          <span>缓存</span>
          <strong>{formatTokens(run.cached_input_tokens)}</strong>
          <small>{ratio}%</small>
        </div>
        <div>
          <span>输出</span>
          <strong>{formatTokens(run.output_tokens)}</strong>
        </div>
        <div>
          <span>请求</span>
          <strong>{run.provider_request_count}</strong>
        </div>
      </div>

      <div
        className="cache-progress"
        role="progressbar"
        aria-label={`${run.agent_type} 缓存命中比例`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={ratio}
      >
        <span style={{ width: `${ratio}%` }} />
      </div>

      {run.summary === null ? null : <p className="agent-run-summary">{run.summary}</p>}
      {run.error_code === null ? null : (
        <p className="error-text">
          {run.error_code} · {run.error_message ?? '未提供错误详情'}
        </p>
      )}

      <details className="agent-run-details">
        <summary>
          <span>逐请求 usage</span>
          <span>{run.provider_requests.length} 条证据</span>
        </summary>
        {run.provider_requests.length === 0 ? (
          <p className="empty-state">本次运行没有外部供应商 usage。</p>
        ) : (
          <ol className="provider-request-list">
            {run.provider_requests.map((request, index) => (
              <RequestUsageRow
                key={`${request.response_id ?? 'request'}-${index}`}
                request={request}
                index={index}
              />
            ))}
          </ol>
        )}
        <dl className="agent-run-identifiers">
          <div>
            <dt>Conversation</dt>
            <dd title={run.conversation_id ?? undefined}>{shortId(run.conversation_id)}</dd>
          </div>
          <div>
            <dt>Cache key</dt>
            <dd title={run.prompt_cache_key ?? undefined}>{shortId(run.prompt_cache_key)}</dd>
          </div>
          <div>
            <dt>最终 Response</dt>
            <dd title={run.provider_response_id ?? undefined}>{shortId(run.provider_response_id)}</dd>
          </div>
          <div>
            <dt>完成时间</dt>
            <dd>{formatDateTime(run.finished_at)}</dd>
          </div>
        </dl>
      </details>
    </article>
  )
}
