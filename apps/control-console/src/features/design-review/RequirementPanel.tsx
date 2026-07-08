import { useState } from 'react'
import { formatApiError, formatDateTime, formatJson } from '../../shared/api/formatters'
import type { DecisionRequest, RequirementSpec } from '../../shared/types/api'

interface RequirementPanelProps {
  requirements: RequirementSpec[]
  onDecideRequirement: (
    requirementId: string,
    action: 'approve' | 'request-changes',
    payload: DecisionRequest,
  ) => Promise<RequirementSpec>
}

/**
 * Requirement Spec 展示和评审面板。
 *
 * 只展示数据库中已有的 `requirement_specs` 记录；为空时明确提示当前
 * 未接入 M4 Requirement Agent。
 */
export function RequirementPanel({ requirements, onDecideRequirement }: RequirementPanelProps) {
  const [comment, setComment] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  const decide = async (requirementId: string, action: 'approve' | 'request-changes') => {
    setMessage(null)
    try {
      await onDecideRequirement(requirementId, action, {
        actor_id: 'control-console',
        reason: comment.trim() === '' ? null : comment.trim(),
      })
      setComment('')
      setMessage(action === 'approve' ? '需求规格已通过。' : '已要求修改需求规格。')
    } catch (error) {
      setMessage(formatApiError(error))
    }
  }

  return (
    <section className="sub-panel" aria-labelledby="requirement-title">
      <h3 id="requirement-title">Requirement Spec / Acceptance Criteria</h3>
      {requirements.length === 0 ? (
        <p className="empty-state">暂无真实 Requirement Spec。M3 不自动生成假需求规格。</p>
      ) : null}
      <label className="decision-comment">
        评审意见
        <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={2} />
      </label>
      {message !== null ? <p className="operation-message">{message}</p> : null}

      {requirements.map((requirement) => (
        <article className="review-card" key={requirement.id}>
          <div className="card-toolbar">
            <div>
              <strong>v{requirement.version}</strong>
              <span className={`review-status status-${requirement.status}`}>{requirement.status}</span>
            </div>
            <small>{formatDateTime(requirement.updated_at)}</small>
          </div>
          <dl className="meta-grid">
            <div>
              <dt>来源类型</dt>
              <dd>{requirement.source_type}</dd>
            </div>
            <div>
              <dt>Requirement ID</dt>
              <dd>{requirement.id}</dd>
            </div>
          </dl>
          <h4>原始需求</h4>
          <p>{requirement.raw_input}</p>
          <h4>User Story</h4>
          <p>{requirement.user_story ?? '未记录'}</p>
          <h4>Acceptance Criteria JSON</h4>
          <pre>{formatJson(requirement.acceptance_criteria_json)}</pre>
          <h4>Constraints JSON</h4>
          <pre>{formatJson(requirement.constraints_json)}</pre>
          <div className="action-row">
            <button type="button" onClick={() => void decide(requirement.id, 'approve')}>
              Approve Requirement
            </button>
            <button type="button" className="danger" onClick={() => void decide(requirement.id, 'request-changes')}>
              Request Changes
            </button>
          </div>
        </article>
      ))}
    </section>
  )
}
