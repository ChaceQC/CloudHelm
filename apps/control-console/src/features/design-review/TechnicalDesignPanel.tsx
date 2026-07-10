import { useState } from 'react'
import { formatApiError, formatDateTime, formatJson } from '../../shared/api/formatters'
import type { DecisionRequest, TechnicalDesign } from '../../shared/types/api'
import { canApproveReview, canRequestReviewChanges } from './reviewActionPolicy'

interface TechnicalDesignPanelProps {
  designs: TechnicalDesign[]
  onDecideDesign: (
    designId: string,
    action: 'approve' | 'request-changes',
    payload: DecisionRequest,
  ) => Promise<TechnicalDesign>
}

/**
 * Technical Design 展示和评审面板。
 *
 * 展示 ADR/设计正文、OpenAPI 草案、DB schema 和 Mermaid 字段；所有字段
 * 均来自后端响应，不在前端补齐示例内容。
 */
export function TechnicalDesignPanel({ designs, onDecideDesign }: TechnicalDesignPanelProps) {
  const [comment, setComment] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const currentVersion = designs.reduce((latest, design) => Math.max(latest, design.version), 0)

  const decide = async (designId: string, action: 'approve' | 'request-changes') => {
    setMessage(null)
    try {
      await onDecideDesign(designId, action, {
        actor_id: 'control-console',
        reason: comment.trim() === '' ? null : comment.trim(),
      })
      setComment('')
      setMessage(action === 'approve' ? '技术设计已通过。' : '已要求修改技术设计。')
    } catch (error) {
      setMessage(formatApiError(error))
    }
  }

  return (
    <section className="sub-panel" aria-labelledby="design-title">
      <h3 id="design-title">Technical Design / ADR</h3>
      {designs.length === 0 ? (
        <p className="empty-state">暂无真实 Technical Design。请先完成 Requirement Agent 后继续推进 Architect Agent。</p>
      ) : null}
      <label className="decision-comment">
        评审意见
        <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={2} />
      </label>
      {message !== null ? <p className="operation-message">{message}</p> : null}

      {designs.map((design) => {
        const isCurrent = design.version === currentVersion
        const canApprove = canApproveReview(design.status, isCurrent)
        const canRequestChanges = canRequestReviewChanges(design.status, isCurrent)
        return (
          <article className="review-card" key={design.id}>
            <div className="card-toolbar">
              <div>
                <strong>
                  {design.design_type} v{design.version}
                </strong>
                <span className={`review-status status-${design.status}`}>{design.status}</span>
                <span className="risk-chip">{design.risk_level}</span>
                {isCurrent ? null : <span className="review-status">历史版本</span>}
              </div>
              <small>{formatDateTime(design.updated_at)}</small>
            </div>
            <h4>设计正文</h4>
            <pre className="markdown-preview">{design.content_markdown}</pre>
            <h4>OpenAPI JSON</h4>
            <pre>{formatJson(design.openapi_json)}</pre>
            <h4>DB Schema JSON</h4>
            <pre>{formatJson(design.db_schema_json)}</pre>
            <h4>Mermaid</h4>
            <pre>{design.mermaid_diagram ?? '未记录'}</pre>
            <div className="action-row">
              <button
                type="button"
                disabled={!canApprove}
                title={canApprove ? '批准当前技术设计' : '只有当前最新版 draft 技术设计可以批准'}
                onClick={() => void decide(design.id, 'approve')}
              >
                批准设计
              </button>
              <button
                type="button"
                className="danger"
                disabled={!canRequestChanges}
                title={canRequestChanges ? '要求修改当前技术设计' : '当前版本不可再次要求修改'}
                onClick={() => void decide(design.id, 'request-changes')}
              >
                要求修改
              </button>
            </div>
          </article>
        )
      })}
    </section>
  )
}
